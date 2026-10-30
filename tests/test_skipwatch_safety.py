"""Independent adversarial checks for evidence integrity, using public-data fakes."""

from __future__ import annotations

import asyncio
import json
import threading
from urllib.parse import parse_qs, urlsplit

import pytest

from nightcrawler.skipwatch_feeds import WALLET, SkipwatchFeeds


def wallet_row(**changes):
    row = {"proxy_wallet": WALLET, "condition_id": "test-market", "token_id": "up-token",
           "side": "BUY", "outcome": "Up", "price": 0.37, "size": 10,
           "timestamp": 999, "slug": "btc-updown-5m-0000000900",
           "transaction_hash": "public-transaction"}
    return row | changes


def observer(*, get=None, now=1000):
    events = []
    feeds = SkipwatchFeeds(on_event=lambda kind, payload, at: events.append((kind, payload, at)),
                          clock=lambda: now, rest_get=get)
    feeds.tokens = {"up-token": ("test-market", "up"), "down-token": ("test-market", "down")}
    return feeds, events


def snapshot(**changes):
    return {"event_type": "book", "asset_id": "up-token", "market": "test-market",
            "timestamp": "999000", "bids": [{"price": ".37", "size": "10"}],
            "asks": [{"price": ".39", "size": "20"}]} | changes


def wallet_page(rows, cursor=None, offset=0):
    return {"data": rows, "pagination": {"next_cursor": cursor, "has_more": cursor is not None,
                                          "limit": 500, "offset": offset}}


def test_failed_later_wallet_page_cannot_publish_partial_evidence_or_advance_watermark():
    replies = [
        wallet_page([wallet_row()], "second-page"),
        wallet_page([wallet_row(proxy_wallet="different-public-wallet")], offset=500),
    ]
    urls = []

    def get(url):
        urls.append(url)
        return replies.pop(0)

    feeds, events = observer(get=get)
    feeds.wallet_watermark = 990
    with pytest.raises(ValueError, match="different observer"):
        asyncio.run(feeds.poll_wallet())
    assert feeds.wallet_watermark == 990
    assert not [event for event in events if event[0] == "wallet_fill"]
    queries = [parse_qs(urlsplit(url).query) for url in urls]
    assert queries[0]["taker_only"] == ["false"]
    assert queries[0]["start"] == queries[1]["start"]
    assert queries[0]["end"] == queries[1]["end"]
    assert queries[1]["cursor"] == ["second-page"]


def test_identical_transaction_hash_never_collapses_opposite_or_duplicate_public_rows():
    rows = [wallet_row(), wallet_row(),
            wallet_row(token_id="down-token", outcome="Down", price=.60)]
    feeds, events = observer(get=lambda url: wallet_page(rows))
    asyncio.run(feeds.poll_wallet())
    initial = [payload for kind, payload, _ in events if kind == "wallet_fill"]
    assert len(initial) == 3
    assert len({row["fill_id"] for row in initial}) == 3
    assert {row["side"] for row in initial} == {"up", "down"}
    assert all(row["maker_taker"] == "unknown" for row in initial)
    asyncio.run(feeds.poll_wallet())
    assert len([event for event in events if event[0] == "wallet_fill"]) == 3


def test_gap_invalidates_depth_until_another_full_snapshot():
    feeds, events = observer()
    feeds.clob_message(snapshot())
    assert "up-token" in feeds.books
    feeds.reset_books("simulated_disconnect")
    events.clear()
    delta = {"event_type": "price_change", "market": "test-market", "timestamp": "999100",
             "price_changes": [{"asset_id": "up-token", "side": "BUY", "price": ".37", "size": "0"}]}
    feeds.clob_message(delta)
    assert "up-token" not in feeds.books
    assert not [update for kind, payload, _ in events if kind == "book_deltas"
                for update in payload["updates"] if update["valid"]]
    feeds.clob_message(snapshot(timestamp="999200"))
    delta["timestamp"] = "999300"
    feeds.clob_message(delta)
    assert feeds.books["up-token"]["bids"] == {}
    assert len([update for kind, payload, _ in events if kind == "book_deltas"
                for update in payload["updates"] if update["valid"]]) == 1


@pytest.mark.parametrize("changes", [{"timestamp": "1006000"}, {"market": "wrong-market"}])
def test_future_or_cross_market_snapshot_cannot_become_valid_book_evidence(changes):
    feeds, events = observer()
    with pytest.raises(ValueError):
        feeds.clob_message(snapshot(**changes))
    assert not feeds.books
    assert not [event for event in events if event[0] == "book_snapshot"]


def test_wallet_timestamp_fraction_does_not_become_invented_execution_precision():
    feeds, events = observer(get=lambda url: wallet_page([wallet_row(timestamp=999.125)]))
    with pytest.raises(ValueError, match="timestamp precision"):
        asyncio.run(feeds.poll_wallet())
    assert not [event for event in events if event[0] == "wallet_fill"]


def test_complete_record_loss_cannot_silently_rewind_a_checkpointed_watcher(tmp_path):
    from nightcrawler.config import Settings
    from nightcrawler.skipwatch import SkipwatchRunner

    settings = Settings(data_dir=tmp_path)
    runner = SkipwatchRunner(settings, threading.Event(), clock=lambda: 1000)
    runner.emit("health", {"source": "wallet", "status": "connected", "wallet_watermark": 1000}, 1000)
    runner.checkpoint()
    checkpoint = json.loads(runner.path.read_text())
    journal = next(runner.directory.glob("*.jsonl"))
    lines = journal.read_bytes().splitlines(keepends=True)
    assert checkpoint["seq"] == len(lines) == 2
    runner.close()
    journal.write_bytes(b"".join(lines[:-1]))
    with pytest.raises(ValueError, match="(?i)(missing|checkpoint|integrity|journal)"):
        restored = SkipwatchRunner(settings, threading.Event(), clock=lambda: 1010)
        restored.close()


def test_post_fill_books_and_bitcoin_cannot_leak_into_historical_descriptive_features():
    from nightcrawler.skipwatch_model import SkipwatchModel

    model = SkipwatchModel(900)
    model.ingest("market", {"market_id": "market", "slug": "window", "start": 900, "end": 1200,
                            "up_token": "up", "down_token": "down"}, 900)
    model.ingest("bitcoin_tick", {"exchange_at": 998, "price": 60_000}, 998.1)
    model.ingest("book_snapshot", {"token_id": "up", "exchange_at": 998,
                                   "bids": [[.40, 10]], "asks": [[.45, 20]], "valid": True}, 998.1)
    model.ingest("bitcoin_tick", {"exchange_at": 998.5, "price": 90_000}, 1001)
    model.ingest("book_snapshot", {"token_id": "up", "exchange_at": 998.5,
                                   "bids": [[.80, 100]], "asks": [[.85, 200]], "valid": True}, 1001)
    features = model.features("market", "up", 999)
    assert features["btc_price"] == 60_000
    assert features["bid"] == .40 and features["ask"] == .45
    assert features["bid_depth"] == 10 and features["ask_depth"] == 20


def test_many_sealed_segments_do_not_open_the_entire_trial_at_once(tmp_path, monkeypatch):
    from pathlib import Path

    from nightcrawler.skipwatch_journal import ObservationJournal, iter_records

    journal = ObservationJournal(tmp_path)
    for offset in range(20):
        journal.append("coverage", {"wallet": True}, 1000 + offset, 1000 + offset, 1000)
        journal.flush(1000)
        journal.seal()
    journal.close()
    original = Path.open
    opened = []

    def counted_open(path, *args, **kwargs):
        if path.name.endswith(".jsonl.gz") and args and args[0] == "rb":
            opened.append(path.name)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", counted_open)
    records = iter_records(tmp_path)
    try:
        assert next(records)["seq"] == 1
        assert len(opened) <= 2, "A three-day trial must not require one open descriptor per segment"
    finally:
        records.close()


def test_same_day_legacy_to_batched_journal_preserves_record_order(tmp_path):
    from nightcrawler.skipwatch_journal import (
        GENESIS,
        ObservationJournal,
        iter_records,
        record_hash,
    )

    first = {"schema": 1, "seq": 1, "kind": "session_started", "session_started_at": 1000,
             "at": 1000, "observed_at": 1000, "payload": {}, "prev_hash": GENESIS}
    first["hash"] = record_hash(first)
    (tmp_path / "1970-01-01.jsonl").write_text(json.dumps(first) + "\n")
    journal = ObservationJournal(tmp_path)
    journal.recover_record(first)
    journal.append("coverage", {"wallet": True}, 1001, 1001, 1000)
    journal.flush(1000)
    journal.close()
    assert [record["seq"] for record in iter_records(tmp_path)] == [1, 2]


@pytest.mark.parametrize("sizes,expected", [([100], "unmatched"), ([10, 10], "ambiguous"), ([10], "inferred")])
def test_print_matching_does_not_turn_an_aggregate_or_ambiguity_into_exact_identity(sizes, expected):
    from nightcrawler.skipwatch_model import SkipwatchModel

    model = SkipwatchModel(900)
    model.ingest("market", {"market_id": "market", "slug": "window", "start": 900, "end": 1200,
                            "up_token": "up", "down_token": "down"}, 900)
    for index, size in enumerate(sizes):
        model.ingest("public_trade", {"token_id": "up", "exchange_at": 999.1 + index * .1,
                                      "price": .37, "size": size, "trade_id": f"print-{index}",
                                      "aggressor": "buy"}, 1000)
    model.ingest("wallet_fill", {"fill_id": "wallet-fill", "market_id": "market", "token_id": "up",
                                 "side": "up", "action": "buy", "exchange_at": 999,
                                 "price": .370000001, "size": 10}, 1001)
    observation = next(event.payload for event in model.due(1006) if event.kind == "wallet_observation")
    assert observation["confidence"] == expected
    assert observation["maker_taker"] == "unknown"
    assert observation["cancellations"] == "unobservable"
    assert "not proven" in observation["matching_precision"]
    assert observation["prior_up"] is None and observation["prior_down"] is None


def test_subsecond_wallet_outage_cannot_disappear_between_scheduled_coverage_samples(tmp_path):
    from nightcrawler.skipwatch_fit import Tape
    from nightcrawler.skipwatch_journal import ObservationJournal

    journal = ObservationJournal(tmp_path)
    journal.append("coverage", {"at": 1000, "wallet": True}, 1000, 1000, 1000)
    journal.append("health", {"source": "wallet", "status": "gap"}, 1000.2, 1000.2, 1000)
    journal.append("health", {"source": "wallet", "status": "connected", "gap_from": 1000.2,
                              "gap_to": 1000.8}, 1000.8, 1000.8, 1000)
    journal.append("coverage", {"at": 1001, "wallet": True}, 1001, 1001, 1000)
    journal.flush(1000)
    journal.close()
    with Tape(tmp_path, 1000, 1002) as tape:
        assert not tape.covered(1000, 1001)
        assert tape.covered(1001, 1002)
