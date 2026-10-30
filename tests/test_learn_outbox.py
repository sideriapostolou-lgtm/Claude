"""learn.db outbox -> receipt chain: every row becomes exactly ONE ``learn`` receipt, across crashes
between the append and the mark, restarts, two drainers and a recreated learn.db (docs/LEARNING.md S2)."""

from __future__ import annotations

import threading

import pytest

from nightcrawler.hashing import verify_receipts
from nightcrawler.learn.store import RECEIPT_KIND, LearnStore, drain_outbox
from nightcrawler.ledger import Ledger


@pytest.fixture
def ledger(tmp_path, fake_clock):
    with Ledger(tmp_path / "nightcrawler.db", clock=fake_clock) as led:
        yield led


@pytest.fixture
def store(tmp_path):
    with LearnStore(tmp_path / "learn" / "learn.db") as st:
        yield st


def learn_receipts(ledger: Ledger) -> list:
    return [r for r in ledger.receipts() if r.kind == RECEIPT_KIND]


def test_each_row_is_receipted_once_with_event_and_outbox_id(store, ledger, fake_clock) -> None:
    ids = [store.add_outbox("tape_root", {"hour": h, "root": "ab" * 32}, fake_clock.now()) for h in range(3)]
    assert drain_outbox(store, ledger) == 3
    assert drain_outbox(store, ledger) == 0  # nothing pending: nothing appended
    receipts = learn_receipts(ledger)
    assert [r.payload["outbox_id"] for r in receipts] == ids
    assert all(r.payload["event"] == "tape_root" and r.payload["store"] == store.uid for r in receipts)
    assert [r.payload["hour"] for r in receipts] == [0, 1, 2]
    assert [row["receipt_seq"] for row in store.outbox()] == [r.seq for r in receipts]
    assert verify_receipts(ledger.receipts()) == (True, None)


def test_a_payload_cannot_forge_its_event_or_outbox_id(store, ledger, fake_clock) -> None:
    oid = store.add_outbox("scoreboard", {"event": "promote", "outbox_id": 999, "store": "x"}, fake_clock.now())
    drain_outbox(store, ledger)
    [r] = learn_receipts(ledger)
    assert (r.payload["event"], r.payload["outbox_id"], r.payload["store"]) == ("scoreboard", oid, store.uid)


def test_exactly_once_across_a_crash_between_append_and_mark(store, ledger, fake_clock, monkeypatch) -> None:
    for h in range(4):
        store.add_outbox("tape_root", {"hour": h}, fake_clock.now())
    real_mark = LearnStore.mark_outbox
    crashes = {"left": 1}

    def crash_once(self, outbox_id, seq, ts):
        if outbox_id == 2 and crashes["left"]:
            crashes["left"] -= 1
            raise RuntimeError("process killed between append and mark")
        return real_mark(self, outbox_id, seq, ts)

    monkeypatch.setattr(LearnStore, "mark_outbox", crash_once)
    with pytest.raises(RuntimeError):
        drain_outbox(store, ledger)
    assert [r.payload["outbox_id"] for r in learn_receipts(ledger)] == [1, 2]  # 2 appended, not marked
    assert [row["receipt_seq"] is not None for row in store.outbox()] == [True, False, False, False]
    assert drain_outbox(store, ledger) == 3  # restart: row 2 is found on the chain, not appended again
    assert [r.payload["outbox_id"] for r in learn_receipts(ledger)] == [1, 2, 3, 4]
    assert all(row["receipt_seq"] is not None for row in store.outbox())


def test_a_crash_before_the_append_appends_on_the_next_drain(store, ledger, fake_clock, monkeypatch) -> None:
    store.add_outbox("tape_seal", {"day": "2026-10-08"}, fake_clock.now())
    real_append = Ledger.append_receipt

    def boom(self, kind, payload, ts=None):
        raise RuntimeError("ledger unavailable")

    monkeypatch.setattr(Ledger, "append_receipt", boom)
    with pytest.raises(RuntimeError):
        drain_outbox(store, ledger)
    monkeypatch.setattr(Ledger, "append_receipt", real_append)
    assert learn_receipts(ledger) == [] and drain_outbox(store, ledger) == 1
    assert len(learn_receipts(ledger)) == 1


def test_two_drainers_never_duplicate(tmp_path, ledger, fake_clock) -> None:
    path = tmp_path / "learn" / "learn.db"
    with LearnStore(path) as writer:
        for h in range(40):
            writer.add_outbox("tape_root", {"hour": h}, fake_clock.now())
    errors: list[BaseException] = []

    def drain() -> None:
        try:
            with LearnStore(path) as st:
                while drain_outbox(st, ledger, limit=3):
                    pass
        except BaseException as exc:  # pragma: no cover - surfaced below
            errors.append(exc)

    threads = [threading.Thread(target=drain) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert not errors
    assert sorted(r.payload["outbox_id"] for r in learn_receipts(ledger)) == list(range(1, 41))


def test_a_recreated_learn_db_is_not_confused_with_old_receipts(tmp_path, ledger, fake_clock) -> None:
    path = tmp_path / "learn" / "learn.db"
    with LearnStore(path) as old:
        old.add_outbox("tape_root", {"hour": 0}, fake_clock.now())
        drain_outbox(old, ledger)
        old_uid = old.uid
    for suffix in ("", "-wal", "-shm"):
        path.with_name(path.name + suffix).unlink(missing_ok=True)
    with LearnStore(path) as new:  # ids restart at 1
        assert new.uid != old_uid
        new.add_outbox("tape_root", {"hour": 1}, fake_clock.now())
        assert drain_outbox(new, ledger) == 1
    assert [(r.payload["store"], r.payload["outbox_id"]) for r in learn_receipts(ledger)] == [
        (old_uid, 1), (new.uid, 1)]


def test_a_register_receipt_fixes_the_variants_t0(store, ledger, fake_clock) -> None:
    store.add_variant("ab" * 32, family="dip_rebound", params={"dip_pct": 0.5}, source="seed", alpha=0.005,
                      threshold=200.0, promotable=True, name="dip 50%", now=fake_clock.now())
    assert store.variant("ab" * 32)["t0"] is None  # not frozen until the chain says so
    fake_clock.advance(5)
    drain_outbox(store, ledger)
    [r] = learn_receipts(ledger)
    assert r.payload["event"] == "register" and r.payload["variant_hash"] == "ab" * 32
    v = store.variant("ab" * 32)
    assert v["t0"] == r.ts and v["register_seq"] == r.seq
