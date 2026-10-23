"""P4b (B1 in packed time slabs): estimator, packer, splitting, decoder, consolidation, runner and resume.

All offline. The runner tests use a fake client that serves a synthetic chain: it parses the pieces out of the
rendered ``sql/b1c.sql`` and answers with compact tuples, as CryptoHouse would."""
import gzip
import json
import re
from pathlib import Path

import numpy as np
import pytest

import b1c
import backfill as B
from cryptohouse import QueryLog, QueryTimeout, Result, ResultTooLarge

FIX = Path(__file__).resolve().parent / "fixtures"

T0 = 1791331200          # 2026-10-03 00:00 UTC
B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def b58(i: int, tag: str) -> str:
    s, n = "", i + 58 * 58
    while n:
        n, r = divmod(n, 58)
        s = B58[r] + s
    return (tag + s + "x" * 40)[:44].replace("0", "o").replace("O", "o").replace("I", "i").replace("l", "L")


# ---------------------------------------------------------------------------------------------- synthetic coins


def make_coins(n=12, seed=3, spacing=900, split="train"):
    rng = np.random.default_rng(seed)
    out = []
    for k in range(n):
        c = T0 + k * spacing + int(rng.integers(0, 600))
        g = c + int(rng.integers(30, 5400))
        out.append({"mint": b58(k, "Mnt"), "pool": b58(k, "Pol"), "c_ts": c, "g_ts": g, "split": split,
                    "rate_curve": float(rng.uniform(0.2, 3.0)), "rate_pool": float(rng.uniform(0.5, 25.0))})
    return out


def coin_obj(d):
    return b1c.Coin(d["mint"], d["pool"], d["c_ts"], d["g_ts"] + b1c.B1_HORIZON_S, d["split"])


def est_for(d):
    lo, hi = d["c_ts"], d["g_ts"] + b1c.B1_HORIZON_S
    pool_nd = {m: d["rate_pool"] * 60 for m in range(d["g_ts"] // 60 * 60, hi, 60)}
    return b1c.estimate_minutes(d["c_ts"], d["g_ts"], lo, hi, curve_n=d["rate_curve"] * (d["g_ts"] - d["c_ts"]),
                                launch_n=10, pool_nd=pool_nd)


def items_for(coins, cov=None):
    cov = cov or {}
    out = []
    for d in coins:
        c = coin_obj(d)
        r = b1c.subtract(c.lo, c.hi, cov.get(c.mint, []))
        if r:
            out.append({"mint": c.mint, "pool": c.pool, "lo": c.lo, "hi": c.hi, "residual": r, "est": est_for(d)})
    return out


def pieces_by_coin(units):
    by = {}
    for u in units:
        mints = [p[0] for p in u.pieces]
        assert len(mints) == len(set(mints)), "a contiguous residual gives at most one piece per coin per unit"
        for m, _p, a, b in u.pieces:
            by.setdefault(m, []).append((a, b))
    return by


# ---------------------------------------------------------------------------------------------- estimator


def test_estimate_conserves_curve_and_pool_counts():
    c, g = T0 + 17, T0 + 17 + 1000
    lo, hi = c, g + 7200
    pool_nd = {m: 10.0 for m in range(g // 60 * 60, g // 60 * 60 + 180 * 60, 60)}   # B2 holds 180 minutes
    est = b1c.estimate_minutes(c, g, lo, hi, curve_n=400, launch_n=100, pool_nd=pool_nd)
    curve = sum(v for m, v in est.items() if m + 60 <= g // 60 * 60)
    assert all(lo - 60 < m < hi for m in est)
    # 0.95 x 400 curve trades; launch share (0.95 x 100) inside [c, c + 120)
    assert sum(est.values()) == pytest.approx(0.95 * 400 + 10.0 * ((hi - g // 60 * 60) / 60), rel=1e-9)
    launch = sum(v for m, v in est.items() if m < c + 120) - 0.95 * 300 * (c // 60 * 60 + 180 - (c + 120)) / (g - c - 120)
    assert launch == pytest.approx(95, rel=0.02)
    assert curve < 0.95 * 400


def test_estimate_fast_graduate_puts_everything_in_the_launch_window():
    est = b1c.estimate_minutes(T0, T0 + 30, T0, T0 + 7230, curve_n=100, launch_n=100, pool_nd={})
    assert sum(est.values()) == pytest.approx(95.0)
    assert set(est) == {T0}


# ---------------------------------------------------------------------------------------------- packer


@pytest.mark.parametrize("target", [920_000, 120_000, 30_000])
def test_pack_pieces_tile_each_window_and_respect_target_and_span(target):
    coins = make_coins(n=16)
    units = b1c.pack(items_for(coins), target=target, max_scan_s=1800)
    assert units
    for u in units:
        single_cell = len(u.pieces) == 1 and u.span <= 60       # one coin-minute above the target: alone
        assert u.est_bytes <= target + 1e-6 or single_cell
        assert u.span <= 1800
        assert all(a < b for _m, _p, a, b in u.pieces)
    by = pieces_by_coin(units)
    for d in coins:
        ps = sorted(by[d["mint"]])
        assert ps[0][0] == d["c_ts"] and ps[-1][1] == d["g_ts"] + 7200
        for (a0, b0), (a1, b1) in zip(ps, ps[1:]):
            assert b0 == a1, "consecutive pieces: no gap, no overlap"
    t0s = [u.t0 for u in units]
    assert t0s == sorted(t0s)


def test_pack_single_huge_minute_gets_its_own_unit():
    d = make_coins(n=1)[0]
    it = items_for([d])[0]
    m = d["g_ts"] // 60 * 60 + 600
    it["est"][m] = 30_000.0                      # 1.29 MB in one coin-minute: above the target
    units = b1c.pack([it], target=920_000)
    big = [u for u in units if any(a <= m < b for _m, _p, a, b in u.pieces) and u.est_bytes > 920_000]
    assert len(big) == 1 and big[0].pieces[0][2] == m and big[0].pieces[0][3] == m + 60


def test_pack_residual_only_and_resumes_after_coverage():
    coins = make_coins(n=6)
    full = b1c.pack(items_for(coins), target=200_000)
    first = full[: len(full) // 2]
    cov = {}
    for u in first:
        for m, _p, a, b in u.pieces:
            cov[m] = b1c.merge_intervals(cov.get(m, []) + [[a, b]])
    rest = b1c.pack(items_for(coins, cov), target=200_000)
    by = pieces_by_coin(first + rest)
    for d in coins:
        assert b1c.covers(by[d["mint"]], d["c_ts"], d["g_ts"] + 7200)
        tot = sum(b - a for a, b in by[d["mint"]])
        assert tot == d["g_ts"] + 7200 - d["c_ts"], "nothing fetched twice"


def test_interval_helpers():
    assert b1c.merge_intervals([[5, 7], [1, 3], [3, 4]]) == [[1, 4], [5, 7]]
    assert b1c.subtract(0, 10, [[2, 3], [5, 12]]) == [(0, 2), (3, 5)]
    assert b1c.covers([[0, 5], [5, 10]], 0, 10) and not b1c.covers([[0, 5], [6, 10]], 0, 10)


def test_split_too_large_and_timeout():
    u = b1c.Unit([["A", "P", 100, 1900], ["B", "Q", 160, 1200]], est_bytes=900_000, est_trades=10)
    left, right = b1c.split_too_large(u)
    assert left.t1 == right.t0 == 960 and left.t0 == 100 and right.t1 == 1900
    one_min = b1c.Unit([["A", "P", 120, 180], ["B", "Q", 120, 180]], 1, 1)
    a, b = b1c.split_too_large(one_min)
    assert [p[0] for p in a.pieces] == ["A"] and [p[0] for p in b.pieces] == ["B"]
    one = b1c.Unit([["A", "P", 120, 180]], 1, 1)
    a, b = b1c.split_too_large(one)
    assert (a.t0, a.t1, b.t0, b.t1) == (120, 150, 150, 180)
    assert b1c.split_too_large(b1c.Unit([["A", "P", 120, 121]], 1, 1)) is None
    # timeouts split at a 15-min anchor (rows read follow the anchors) ...
    w = b1c.Unit([["A", "P", T0 + 420, T0 + 2220]], 1, 1)          # 00:07 -> 00:37
    a, b = b1c.split_timeout(w)
    assert a.t1 == T0 + 900 and b.t0 == T0 + 900
    # ... and never inside one anchor bucket
    assert b1c.split_timeout(b1c.Unit([["A", "P", T0 + 60, T0 + 840]], 1, 1)) is None


# ---------------------------------------------------------------------------------------------- decoder


def test_decoder_matches_the_old_format_on_real_rows():
    fx = json.loads((FIX / "b1c_m2_pilot.json").read_text())
    pc = fx["pilot_columns"]
    n = 0
    for r in fx["rows"]:
        d = dict(zip(fx["columns"], r))
        dec = b1c.decode_trades(d["lo"], d["trades"])
        old = sorted(fx["pilot"][d["mint"]], key=lambda t: t[:4])
        assert len(old) == len(dec["slot"]) == d["n_trades"] > 0
        for i, t in enumerate(old):
            o = dict(zip(pc, t))
            for k in ("slot", "tx_idx", "pix", "ix", "ts", "venue", "is_buy", "wallet_h"):
                assert int(dec[k][i]) == int(o[k]), k
            assert abs(int(dec["usol"][i]) - o["usol"]) < 1000            # <= 1e-6 SOL
            assert abs(int(dec["fees"][i]) - o["fees"]) < 1000
            assert abs(int(dec["tok"][i]) - o["tok"]) <= 500_000          # <= 0.5 token
            assert abs(int(dec["y0"][i]) - o["y0"]) <= 500_000
            assert abs(int(dec["x0"][i]) - o["x0"]) <= 1e-7 * o["x0"]
            if o["virt_ksol"]:                                             # pre-patch pilot: 0 on sells
                assert int(dec["virt_ksol"][i]) == o["virt_ksol"]
            n += 1
    assert n == 11


def test_decoder_flags_and_units():
    t = [[7, 3, 2, 1, 65, 2, 2**64 - 1, 1234567, 4, 3.0e10, 1073, 5, 17584]]   # curve buy
    d = b1c.decode_trades(1000, t)
    assert (d["venue"][0], d["is_buy"][0], d["ts"][0]) == (0, 1, 1065)
    assert d["wallet_h"].dtype == np.uint64 and int(d["wallet_h"][0]) == 2**64 - 1
    assert (d["usol"][0], d["tok"][0], d["y0"][0], d["fees"][0], d["x0"][0]) == (1234567000, 4_000_000,
                                                                                    1_073_000_000, 5000, 30_000_000_000)
    s = b1c.decode_trades(1000, [[7, 3, 2, 1, 0, 1, 1, 1, 1, 1.0, 1, 1, 0]])
    assert (s["venue"][0], s["is_buy"][0]) == (1, 0)


def test_virt_forward_fill_only_after_the_first_value():
    venue = np.array([0, 1, 1, 1, 0, 1, 1, 1])
    virt = np.array([0, 0, 17584, 0, 0, 0, 17590, 0])
    v, n = b1c.ffill_virt(venue, virt)
    assert v.tolist() == [0, 0, 17584, 17584, 0, 17584, 17590, 17590] and n == 3


def test_sort_dedup_drops_repeated_keys():
    cols = b1c.decode_trades(0, [[5, 1, 0, 2, 1, 1, 9, 1, 1, 1.0, 1, 1, 1], [4, 1, 0, 2, 1, 1, 9, 1, 1, 1.0, 1, 1, 1],
                                 [5, 1, 0, 2, 1, 1, 9, 1, 1, 1.0, 1, 1, 1]])
    s, nd = b1c.sort_dedup(cols)
    assert s["slot"].tolist() == [4, 5] and nd == 1


def test_sql_renders_with_overflow_guard_and_per_piece_carry():
    from decode import render_sql, sql_in, sql_tuples
    sql = render_sql("b1c", win=sql_tuples([(b58(0, "Mnt"), b58(0, "Pol"), T0, T0 + 600)]), mints=sql_in([b58(0, "Mnt")]),
                     s0=1, s1=2, t0=B.utc(T0), t1=B.utc(T0 + 600), min_usol=b1c.MIN_USOL)
    assert "$" not in sql.replace("$$", "")
    assert "n_overflow" in sql and "usol >= 4294967295000" in sql and "ts - ts_lo > 65535" in sql
    assert sql.count("PARTITION BY mint, ts_lo, venue") == 3 and "GROUP BY mint, ts_lo" in sql
    body = "\n".join(line for line in sql.splitlines() if not line.lstrip().startswith("--"))
    assert "wallet_dict" not in body and "max_trades" not in body and "minutes" not in body


# ---------------------------------------------------------------------------------------------- fake chain + runner

WIN_RE = re.compile(r"\('([1-9A-HJ-NP-Za-km-z]+)','([1-9A-HJ-NP-Za-km-z]+)',(\d+),(\d+)\)")
V_K = 17584


def tape(d, k):
    """Deterministic chain for coin k: a trade every 7 s from c + 3; curve before g, pool after."""
    out, j = [], 0
    ts = d["c_ts"] + 3
    while ts < d["g_ts"] + b1c.B1_HORIZON_S + 300:
        venue = 0 if ts < d["g_ts"] else 1
        is_buy = int(j % 3 != 1)
        out.append({"slot": 2 * (ts - T0) + 400_000_000, "tx_idx": 10 + k, "pix": j % 4, "ix": j % 7, "ts": ts,
                    "venue": venue, "is_buy": is_buy, "w": 1000 + (j * 31 + k) % 97, "usol": 20_000_000 + 1000 * j,
                    "tok": 123_456_789 + j, "x0": 30_000_000_000 + 1000 * j, "y0": 1_000_000_000_000 - j})
        j += 1
        ts += 7
    return out


class FakeChain:
    def __init__(self, tmp_path, coins, script=()):
        self.qlog = QueryLog(tmp_path / "log.jsonl")
        self.coins = {d["mint"]: (k, d) for k, d in enumerate(coins)}
        self.tapes = {d["mint"]: tape(d, k) for k, d in enumerate(coins)}
        self.script = list(script)     # [(predicate(tag, pieces) -> exc or None)]
        self.tags, self.pieces = [], []
        self.overflow = set()

    def usage(self):
        return {}

    def query(self, sql, tag=""):
        pieces = [(m, p, int(a), int(b)) for m, p, a, b in WIN_RE.findall(sql)]
        self.tags.append(tag)
        for i, fn in enumerate(self.script):
            exc = fn(tag, pieces)
            if exc is not None:
                self.script.pop(i)
                raise exc(159, "scripted")
        self.pieces.append(pieces)
        rows = []
        for m, _p, a, b in pieces:
            tr = [t for t in self.tapes[m] if a <= t["ts"] < b]
            if not tr:
                continue
            seen_buy, out = False, []
            for t in tr:
                if t["venue"] == 1 and t["is_buy"]:
                    seen_buy = True
                virt = V_K if t["venue"] == 1 and seen_buy else 0
                out.append([t["slot"], t["tx_idx"], t["pix"], t["ix"], t["ts"] - a, t["venue"] + 2 * t["is_buy"],
                            t["w"], t["usol"] // 1000, (t["tok"] + 500_000) // 1_000_000, float(np.float32(t["x0"])),
                            (t["y0"] + 500_000) // 1_000_000, 0, virt])
            rows.append([m, a, len(out), out, 43 * len(out), 1 if m in self.overflow else 0])
        return Result(["mint", "lo", "n_trades", "trades", "b_trades", "n_overflow"], [], rows, 1.0, 1000, 0, 1.0)


def runner_for(tmp_path, coins, splits=("train",), script=(), max_queries=None, ch=None, target=150_000,
               retry_errors=False):
    sm = {str(t): [t, t + 1] for t in range(T0 - 6 * 3600, T0 + 30 * 3600, 900)}
    (tmp_path / "slotmap.json").write_text(json.dumps(sm))
    ch = ch or FakeChain(tmp_path, coins, script)
    bf = B.Backfill(tmp_path, ch, None, max_queries, state_name="state_b1.json")
    sel = {}
    for d in coins:
        sel.setdefault(d["split"], []).append(coin_obj(d))
    est = {d["mint"]: est_for(d) for d in coins}
    r = b1c.Runner(bf, sel, list(splits), est, target=target, timeout_backoff_s=0, retry_errors=retry_errors)
    return r, bf, ch, sel


def grads_of(coins):
    return {d["mint"]: {"mint": d["mint"], "pool": d["pool"], "c_ts": d["c_ts"], "g_ts": d["g_ts"], "has_create": 1}
            for d in coins}


def pool_nd_of(ch):
    out = {}
    for m, (k, d) in ch.coins.items():
        nd = {}
        for t in ch.tapes[m]:
            if t["venue"] == 1 and t["ts"] < d["g_ts"] + 180 * 60:
                mm = t["ts"] // 60 * 60
                nd[mm] = nd.get(mm, 0) + 1
        out[d["pool"]] = nd
    return out


def test_runner_fetches_every_window_and_consolidates_complete_coins(tmp_path):
    coins = make_coins(n=5)
    r, bf, ch, sel = runner_for(tmp_path, coins)
    assert r.run()
    assert len(ch.tags) == len(list((tmp_path / "raw" / "b1c").glob("*.json.gz")))
    assert all(t.startswith("b1c:train:") for t in ch.tags)
    assert (tmp_path / "state_b1.json").exists() and not (tmp_path / "state.json").exists()
    for d in coins:
        assert b1c.covers(r.st["cov"][d["mint"]], d["c_ts"], d["g_ts"] + 7200)
    res = b1c.consolidate_b1(tmp_path, grads_of(coins), pool_nd_of(ch), sel)
    rows = {x["mint"]: x for x in res["coins"]}
    assert all(rows[d["mint"]]["complete"] for d in coins)
    tr = res["trades"]
    for d in coins:
        exp = [t for t in ch.tapes[d["mint"]] if t["ts"] < d["g_ts"] + 7200]
        got = tr["mint"] == d["mint"]
        assert got.sum() == len(exp) == rows[d["mint"]]["n_trades"]
        ts = tr["ts"][got]
        assert ts.min() >= d["c_ts"] and ts.max() < d["g_ts"] + 7200
        assert rows[d["mint"]]["gate_ok"] is True and rows[d["mint"]]["gate_abs_diff"] == 0
        # every pool row after the coin's first pool buy carries the virtual reserve (piece starts forward-filled)
        pool = tr["venue"][got] == 1
        v = tr["virt_ksol"][got][pool]
        first = np.flatnonzero(v > 0)[0]
        assert (v[first:] == V_K).all()
    assert res["manifest"]["train"]["frac"] == 1.0


def test_result_too_large_splits_and_still_covers(tmp_path):
    coins = make_coins(n=4)
    fired = []

    def big(tag, pieces):
        if not fired:
            fired.append(tag)
            return ResultTooLarge
        return None
    r, bf, ch, sel = runner_for(tmp_path, coins, script=[big])
    assert r.run()
    assert r.run_stats["train"]["splits_large"] == 1
    assert len(ch.tags) == len(ch.pieces) + 1
    for d in coins:
        assert b1c.covers(r.st["cov"][d["mint"]], d["c_ts"], d["g_ts"] + 7200)


def test_timeout_splits_at_an_anchor_or_defers_then_errors(tmp_path):
    coins = make_coins(n=3)
    state = {"n": 0}

    def slow_first(tag, pieces):
        if state["n"] == 0:
            state["n"] += 1
            return QueryTimeout
        return None
    r, bf, ch, sel = runner_for(tmp_path, coins, script=[slow_first])
    assert r.run()
    assert r.run_stats["train"]["splits_timeout"] + r.run_stats["train"]["timeouts_deferred"] == 1
    for d in coins:
        assert b1c.covers(r.st["cov"][d["mint"]], d["c_ts"], d["g_ts"] + 7200)
    # a coin whose one-anchor unit always times out ends as an error after TIMEOUT_TRIES, the others complete
    coins = make_coins(n=2, spacing=20_000)
    victim = coins[0]["mint"]

    def always(tag, pieces):
        if any(p[0] == victim for p in pieces):
            return QueryTimeout
        return None
    (tmp_path / "b").mkdir()
    r2, bf2, ch2, _ = runner_for(tmp_path / "b", coins, script=[always] * 100)
    assert r2.run()
    assert victim in r2.st["err"] and "timeout" in r2.st["err"][victim]["msg"]
    assert coins[1]["mint"] not in r2.st["err"]


def test_overflow_marks_the_coin_and_consolidation_never_writes_it(tmp_path):
    coins = make_coins(n=3)
    ch = FakeChain(tmp_path, coins)
    ch.overflow.add(coins[1]["mint"])
    r, bf, ch, sel = runner_for(tmp_path, coins, ch=ch)
    assert r.run()
    assert coins[1]["mint"] in r.st["err"] and "overflow" in r.st["err"][coins[1]["mint"]]["msg"]
    res = b1c.consolidate_b1(tmp_path, grads_of(coins), pool_nd_of(ch), sel)
    rows = {x["mint"]: x for x in res["coins"]}
    assert not rows[coins[1]["mint"]]["complete"] and rows[coins[1]["mint"]]["overflow_pieces"] >= 1
    assert coins[1]["mint"] not in set(res["trades"]["mint"])
    assert res["manifest"]["train"]["complete"] == 2


def test_resume_after_stop_fetches_only_the_rest_and_partial_coins_are_not_written(tmp_path):
    coins = make_coins(n=6)
    r, bf, ch, sel = runner_for(tmp_path, coins, max_queries=2)
    assert not r.run()
    assert len(ch.tags) == 2
    res = b1c.consolidate_b1(tmp_path, grads_of(coins), pool_nd_of(ch), sel)
    partial = [x for x in res["coins"] if not x["complete"]]
    assert partial and all(x["mint"] not in set(res["trades"]["mint"] if res["trades"] else []) for x in partial)
    # restart with a new process: re-pack the residual, never re-fetch a covered second
    ch2 = FakeChain(tmp_path, coins)
    r2, bf2, ch2, _ = runner_for(tmp_path, coins, ch=ch2)
    assert r2.run()
    fetched = {}
    for pieces in ch.pieces + ch2.pieces:
        for m, _p, a, b in pieces:
            fetched.setdefault(m, []).append((a, b))
    for d in coins:
        tot = sum(b - a for a, b in fetched[d["mint"]])
        assert tot == d["g_ts"] + 7200 - d["c_ts"]
        assert b1c.covers(fetched[d["mint"]], d["c_ts"], d["g_ts"] + 7200)
    res = b1c.consolidate_b1(tmp_path, grads_of(coins), pool_nd_of(ch2), sel)
    assert all(x["complete"] for x in res["coins"]) and res["summary"]["b1_gate_flagged"] == 0


def test_splits_run_strictly_in_order(tmp_path):
    coins = make_coins(n=3, split="val") + [dict(d, mint=b58(50 + i, "Trn"), pool=b58(50 + i, "Tpl"), split="train")
                                            for i, d in enumerate(make_coins(n=3, seed=9))]
    r, bf, ch, sel = runner_for(tmp_path, coins, splits=("train", "val"))
    assert r.run()
    kinds = [t.split(":")[1] for t in ch.tags]
    assert kinds == sorted(kinds, key=lambda s: ("train", "val").index(s)) and set(kinds) == {"train", "val"}


def test_consolidate_writes_b1_parquet_atomically_with_schema(tmp_path):
    import pandas as pd
    coins = make_coins(n=3)
    r, bf, ch, sel = runner_for(tmp_path, coins)
    assert r.run()
    (tmp_path / "b1_select.json").write_text(json.dumps(
        {"splits": {"train": {"coins": [[c.mint, c.pool, c.lo, c.hi] for c in sel["train"]]}}}))
    bars = [{"pool": d["pool"], "minute_ts": m, "n_buys": n, "n_sells": 0, "n_dust": 0}
            for d in coins for m, n in pool_nd_of(ch)[d["pool"]].items()]
    s = B.consolidate_b1(tmp_path, grads_of(coins), bars)
    assert s["b1_coins_complete"] == 3
    tr = pd.read_parquet(tmp_path / "b1_trades.parquet")
    assert list(tr.columns) == [k for k, _ in B.B1_SCHEMA]
    assert str(tr["wallet_h"].dtype) == "uint64" and str(tr["slot"].dtype) == "int64"
    co = pd.read_parquet(tmp_path / "b1_coins.parquet")
    assert co["complete"].all() and (co["split"] == "train").all()
    man = json.loads((tmp_path / "b1_manifest.json").read_text())
    assert man["splits"]["train"] == {**man["splits"]["train"], "selected": 3, "complete": 3, "frac": 1.0}
    assert not list(tmp_path.glob(".*.tmp"))


def test_consolidate_lock_is_exclusive(tmp_path):
    import fcntl
    with B.consolidate_lock(tmp_path):
        with open(tmp_path / "consolidate.lock", "a+") as f:
            with pytest.raises(BlockingIOError):
                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    with open(tmp_path / "consolidate.lock", "a+") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def test_chunk_saved_before_state(tmp_path, monkeypatch):
    coins = make_coins(n=1)
    r, bf, ch, sel = runner_for(tmp_path, coins)
    seen = []
    orig = bf.store.save_state

    def spy():
        seen.append(len(list((tmp_path / "raw" / "b1c").glob("*.json.gz"))) if (tmp_path / "raw" / "b1c").exists() else 0)
        orig()
    monkeypatch.setattr(bf.store, "save_state", spy)
    assert r.run()
    assert seen and seen[0] >= 1
    with gzip.open(next((tmp_path / "raw" / "b1c").glob("*.json.gz")), "rt") as f:
        p = json.load(f)
    assert p["pieces"] and p["params"]["min_usol"] == b1c.MIN_USOL and p["split"] == "train"


# ---------------------------------------------------------------------------------------------- P1 alignment


class NullCH:
    def __init__(self, tmp_path):
        self.qlog = QueryLog(tmp_path / "log.jsonl")

    def usage(self):
        return {}

    def query(self, sql, tag=""):
        raise AssertionError(f"no query expected: {tag}")


@pytest.mark.parametrize("days", [7, 8.1, 8.37])
def test_p1_start_is_hour_aligned(tmp_path, days, monkeypatch):
    now = T0 + 6 * 86400 + 1234
    sm = {str(t): [t, t + 1] for t in range(T0 - 10 * 86400, now + 3600, 900)}
    (tmp_path / "slotmap.json").write_text(json.dumps(sm))
    bf = B.Backfill(tmp_path, NullCH(tmp_path), None, 0)
    bf.p1(days, B.floor_to(now, 900), census_first=False)
    rs = bf.store.state["ranges"]
    assert all(a % 3600 == 0 and b % 3600 == 0 for a, b in rs)
    assert min(a for a, _ in rs) == B.floor_to(B.floor_to(now, 3600) - int(days * 86400), 3600)
    bf.p1(1, B.floor_to(now, 900), census_first=False, since=B.parse_utc("2026-10-01 00:20"))
    assert min(a for a, _ in bf.store.state["ranges"]) == B.parse_utc("2026-10-01")


def test_store_state_names_are_separate(tmp_path):
    a, b = B.Store(tmp_path), B.Store(tmp_path, "state_b1.json")
    a.state["curve"]["1"] = {"done": True}
    a.save_state()
    b.state.setdefault("b1c", {})["x"] = 1
    b.save_state()
    assert "b1c" not in json.loads((tmp_path / "state.json").read_text())
    assert json.loads((tmp_path / "state_b1.json").read_text())["b1c"] == {"x": 1}


def test_old_p4_refuses(tmp_path):
    assert B.main(["--phase", "P4", "--out", str(tmp_path)]) == 2
