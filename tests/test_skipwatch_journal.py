"""Batched physical durability without dropping public depth changes."""

from __future__ import annotations

import json

import pytest

from nightcrawler.skipwatch_journal import (
    ObservationJournal,
    iter_records,
    source_paths,
)


def test_many_events_share_one_hash_batch_then_replay_losslessly_after_compression(tmp_path):
    journal = ObservationJournal(tmp_path)
    for index in range(500):
        journal.append("book_deltas", {"updates": [{"price": .4, "size": index}]}, 1000, 1000, 900)
    assert not source_paths(tmp_path)
    assert journal.durable_seq == 0
    journal.flush(900)
    assert len(source_paths(tmp_path)) == 1
    envelope = json.loads(source_paths(tmp_path)[0].read_text())
    assert envelope["first_seq"] == 1 and envelope["last_seq"] == 500
    journal.seal()
    assert source_paths(tmp_path)[0].name.endswith(".jsonl.gz")
    rows = list(iter_records(tmp_path))
    assert len(rows) == 500 and len({row["hash"] for row in rows}) == 1
    assert [row["payload"]["updates"][0]["size"] for row in rows] == list(range(500))
    journal.close()


def test_reader_sees_durable_prefix_even_if_active_file_grows_during_scan(tmp_path):
    journal = ObservationJournal(tmp_path)
    for at in [1000, 1001]:
        journal.append("coverage", {"wallet": True}, at, at, 900)
    journal.flush(900)
    records = iter_records(tmp_path)
    assert next(records)["seq"] == 1
    journal.append("coverage", {"wallet": False}, 1002, 1002, 900)
    journal.flush(900)
    assert [row["seq"] for row in records] == [2]
    assert len(list(iter_records(tmp_path))) == 3
    journal.close()


def test_modified_batch_is_rejected_before_any_row_is_yielded(tmp_path):
    journal = ObservationJournal(tmp_path)
    journal.append("coverage", {"wallet": True}, 1000, 1000, 900)
    journal.flush(900)
    path = source_paths(tmp_path)[0]
    path.write_text(path.read_text().replace('"wallet":true', '"wallet":false'))
    with pytest.raises(ValueError, match="integrity"):
        next(iter_records(tmp_path))
    journal.close()


def test_utc_rotation_seals_prior_day_without_deleting_observations(tmp_path):
    journal = ObservationJournal(tmp_path)
    journal.append("coverage", {}, 86399, 86399, 86000)
    journal.append("coverage", {}, 86400, 86400, 86000)
    journal.flush(86000)
    paths = source_paths(tmp_path)
    assert paths[0].name.startswith("1970-01-01") and paths[0].name.endswith(".gz")
    assert paths[1].name.startswith("1970-01-02")
    assert [row["seq"] for row in iter_records(tmp_path)] == [1, 2]
    journal.close()
