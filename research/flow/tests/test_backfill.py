"""Backfill control flow with a scripted fake client: splits on timeout / size, checkpoint and resume."""
import json

import pytest

import backfill as B
from cryptohouse import QueryLog, QueryTimeout, Result, ResultTooLarge

H0 = 1791460800  # 2026-10-08 12:00 UTC
POOL = "6MGN7YayGf7oUygpg9a8FVxE7vXKtvZeRwTk5YrA9Kbo"
MINT = "HqJ4C36psbzNHbgS6YZveCyRHcWNKpptSEP1Jq7Cpump"


class FakeCH:
    def __init__(self, tmp_path, script):
        self.qlog = QueryLog(tmp_path / "log.jsonl")
        self.script = script      # list of (tag_prefix, exception or None)
        self.tags = []

    def usage(self):
        return {}

    def query(self, sql, tag=""):
        self.tags.append(tag)
        for i, (prefix, exc) in enumerate(self.script):
            if tag.startswith(prefix):
                self.script.pop(i)
                if exc:
                    raise exc(159, "scripted")
                break
        if tag.startswith("curve:"):
            cols = ["mint", "g_ts", "has_create", "c_ts", "pool"]
            rows = [[MINT, H0 + 100, 1, H0 + 100, POOL]] if tag.startswith(f"curve:{B.utc(H0)}") else []
            return Result(cols, [], rows, 1.0, 0, 0, 1.0)
        if tag.startswith("b2:"):
            return Result(["pool", "mint", "g_ts", "bars"], [], [[POOL, MINT, H0 + 100, []]], 1.0, 0, 0, 1.0)
        raise AssertionError(tag)


def _bf(tmp_path, script, max_queries=None):
    sm = {str(t): [t, t + 1] for t in range(H0 - 6 * 3600, H0 + 6 * 3600, 900)}
    (tmp_path / "slotmap.json").write_text(json.dumps(sm))
    ch = FakeCH(tmp_path, script)
    return B.Backfill(tmp_path, ch, None, max_queries), ch


def test_curve_timeout_splits_in_halves(tmp_path):
    bf, ch = _bf(tmp_path, [("curve:", QueryTimeout)])
    assert bf.run_curve_hour(H0)
    st = bf.store.state["curve"][str(H0)]
    assert st["done"] and sorted(st["parts"]) == [f"{H0}-{H0 + 1800}", f"{H0 + 1800}-{H0 + 3600}"]
    assert len(ch.tags) == 3
    assert MINT in bf.graduates()


def test_b2_waits_for_curve_and_splits_time(tmp_path):
    bf, ch = _bf(tmp_path, [("b2:", QueryTimeout)])
    for h in range(H0 - 3 * 3600, H0 + 3600, 3600):
        assert bf.run_curve_hour(h)
    assert bf.b2_ready(H0) and bf.b2_pools_for(H0) == [(POOL, MINT, H0 + 100)]
    assert bf.run_b2_hour(H0)
    st = bf.store.state["b2"][str(H0)]
    assert st["done"] and st["done_pools"] == [POOL]
    assert [t for t in ch.tags if t.startswith("b2")] == [f"b2:{B.utc(H0)}:1", f"b2:{B.utc(H0)}:1",
                                                         f"b2:{B.utc(H0 + 1800)}:1"]
    assert len(list((tmp_path / "raw" / "b2").glob("*.json.gz"))) == 2


def test_b2_resume_after_stop_does_not_skip_second_half(tmp_path):
    bf, ch = _bf(tmp_path, [("b2:", QueryTimeout)])
    for h in range(H0 - 3 * 3600, H0 + 3600, 3600):
        bf.run_curve_hour(h)
    bf.max_queries = bf.n_queries + 2           # the timeout + the first half, then stop
    assert not bf.run_b2_hour(H0)
    assert bf.store.state["b2"][str(H0)]["done_pools"] == []
    bf2, ch2 = _bf(tmp_path, [])
    assert bf2.run_b2_hour(H0)
    # resumed: neither the full hour nor the finished first half is re-queried, only the second half
    assert [t for t in ch2.tags if t.startswith("b2")] == [f"b2:{B.utc(H0 + 1800)}:1"]
    assert bf2.store.state["b2"][str(H0)]["done_pools"] == [POOL]


def test_b2_result_too_large_halves_pool_batch(tmp_path):
    bf, ch = _bf(tmp_path, [("b2:", ResultTooLarge)])
    batch = [(POOL, MINT, H0 + 100), (POOL[:-1] + "p", MINT, H0 + 200)]
    st = {"done_pools": [], "parts": {}}
    assert bf._run_b2_batch(H0, H0, H0 + 3600, batch, st)
    assert sorted(st["done_pools"]) == sorted(b[0] for b in batch)
    assert [t.split(":")[-1] for t in ch.tags] == ["2", "1", "1"]
