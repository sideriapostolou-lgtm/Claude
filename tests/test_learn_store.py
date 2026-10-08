"""learn.db schema, migrations, the fetch queue, the learner lease and the evidence/scoreboard tables."""

from __future__ import annotations

import sqlite3

import pytest

from nightcrawler.learn.store import SCHEMA_VERSION, LearnStore

T = 1_791_475_200.0


@pytest.fixture
def store(tmp_path):
    with LearnStore(tmp_path / "learn" / "learn.db") as st:
        yield st


def test_schema_is_versioned_and_reopening_keeps_data(tmp_path) -> None:
    path = tmp_path / "learn" / "learn.db"
    with LearnStore(path) as st:
        assert st.add_coin("M1", created_ts=T, first_seen_ts=T + 60, day="2026-10-08", launch={"symbol": "A"})
        uid = st.uid
    with LearnStore(path) as st:
        assert st.uid == uid and st.coin("M1")["launch"] == {"symbol": "A"}
    assert sqlite3.connect(path).execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION


def test_coins_are_enrolled_once(store) -> None:
    assert store.add_coin("M1", created_ts=T, first_seen_ts=T, day="2026-10-08", quote_mint="Q", mayhem=True)
    assert not store.add_coin("M1", created_ts=T + 1, first_seen_ts=T + 9, day="2026-10-09")
    coin = store.coin("M1")
    assert (coin["created_ts"], coin["first_seen_ts"], coin["status"], coin["mayhem"]) == (T, T, "open", True)
    store.set_coin_status("M1", "closed")
    assert [c["mint"] for c in store.coins(day="2026-10-08", status="closed")] == ["M1"]
    assert store.coin("nope") is None


def test_fetch_queue_due_retry_fail_and_finish(store) -> None:
    store.add_coin("M1", created_ts=T, first_seen_ts=T, day="2026-10-08")
    for due in (T + 300, T + 900):
        store.schedule("M1", "snaps", due)
    store.schedule("M1", "snaps", T + 300)  # idempotent
    assert [(d["mint"], d["due_ts"]) for d in store.due(T + 600)] == [("M1", T + 300)]
    assert store.retry_fetch("M1", "snaps", T + 300, next_try_ts=T + 1000) == 1
    assert [d["due_ts"] for d in store.due(T + 900)] == [T + 900]  # the retried one waits for its backoff
    assert [d["due_ts"] for d in store.due(T + 1000)] == [T + 300, T + 900]
    store.finish_fetch("M1", "snaps", T + 900, T + 1001)
    store.fail_fetch("M1", "snaps", T + 300, T + 1002)
    assert store.due(T + 10_000) == [] and store.open_fetches("M1") == 0


def test_the_learner_lease_is_exclusive_until_stale(store) -> None:
    assert store.acquire_lease("learner", pid=10, now=T, stale_s=300)
    assert store.acquire_lease("learner", pid=10, now=T + 10, stale_s=300)  # the holder renews
    assert not store.acquire_lease("learner", pid=11, now=T + 100, stale_s=300)
    assert store.acquire_lease("learner", pid=11, now=T + 400, stale_s=300)  # stale: taken over
    store.release_lease("learner", pid=10)  # not the holder: no effect
    assert not store.acquire_lease("learner", pid=12, now=T + 401, stale_s=300)
    store.release_lease("learner", pid=11)
    assert store.acquire_lease("learner", pid=12, now=T + 402, stale_s=300)


def test_evidence_is_one_row_per_variant_coin_and_pricing_in_exit_order(store) -> None:
    base = {"variant_hash": "v1", "pricing": "replay", "entry_ts": T, "x": 0.1, "x_raw": 0.1, "x_stress": 0.08,
            "gross": 0.12, "cost": 0.02, "sim_hash": "s", "cost_scale_ver": 1}
    store.put_evidence({**base, "mint": "B", "exit_ts": T + 50})
    store.put_evidence({**base, "mint": "A", "exit_ts": T + 50})
    store.put_evidence({**base, "mint": "C", "exit_ts": T + 10, "x": -0.2})
    store.put_evidence({**base, "mint": "C", "exit_ts": T + 10, "x": -0.3})  # recomputed: replaced
    assert [(e["mint"], e["x"]) for e in store.evidence("v1")] == [("C", -0.3), ("A", 0.1), ("B", 0.1)]
    assert store.evidence("v1", pricing="paper") == [] and store.evidence_mints("v1") == {"A", "B", "C"}


def test_scoreboard_rows_by_day(store) -> None:
    store.put_scoreboard("2026-10-08", "v1", {"n": 3, "log_e": 0.5, "status": "testing"}, T)
    store.put_scoreboard("2026-10-09", "v1", {"n": 4, "log_e": 0.7, "status": "testing"}, T + 86400)
    assert store.latest_scoreboard_day() == "2026-10-09"
    assert store.scoreboard("2026-10-09") == [{"day": "2026-10-09", "variant_hash": "v1", "n": 4, "log_e": 0.7,
                                               "status": "testing", "updated_ts": T + 86400}]


def test_meta_round_trips_json(store) -> None:
    assert store.get_meta("tape.offsets", {}) == {}
    store.set_meta("tape.offsets", {"2026-10-08/candles.jsonl": 120})
    assert store.get_meta("tape.offsets") == {"2026-10-08/candles.jsonl": 120}


def test_a_read_only_store_never_creates_the_file(tmp_path) -> None:
    path = tmp_path / "learn" / "learn.db"
    with pytest.raises(FileNotFoundError):
        LearnStore(path, readonly=True)
    assert not path.exists()
    with LearnStore(path) as st:
        st.set_meta("k", 1)
    with LearnStore(path, readonly=True) as ro:
        assert ro.get_meta("k") == 1
        with pytest.raises(sqlite3.OperationalError):
            ro.set_meta("k", 2)
