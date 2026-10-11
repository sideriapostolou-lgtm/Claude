"""Ledger: SQLite storage, hash-chained receipts, tamper detection, export, thread-safety."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import sqlite3
import threading
from pathlib import Path

import pytest
from fakes import FakeClock

from nightcrawler.hashing import GENESIS_HASH, receipt_hash, verify_receipts
from nightcrawler.ledger import SCHEMA_VERSION, Ledger, LedgerError
from nightcrawler.models import (
    Decision,
    EquityPoint,
    Fill,
    Position,
    SafetyReport,
    TokenCandidate,
    Verdict,
)

NOW = 1_791_475_200.0
MINT_A = "HiGGSmintAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
MINT_B = "HooKimintBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB"


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "data" / "nightcrawler.db"


@pytest.fixture
def ledger(db_path: Path, fake_clock: FakeClock) -> Ledger:
    with Ledger(db_path, clock=fake_clock) as led:
        yield led


def make_fill(fill_id: str = "fill_1", *, side: str = "buy", mint: str = MINT_A, ts: float = NOW,
              position_id: str | None = "pos_1", sol: int = 100_000_000, tokens: int = 5_000_000) -> Fill:
    return Fill(id=fill_id, mode="paper", side=side, mint=mint, sol_lamports=sol, token_amount=tokens,
                token_decimals=6, price_usd=0.004, sol_usd=200.0, fees_lamports=300_000, platform_fee_bps=10,
                price_impact_pct=1.2, signature=None, request_id="req", ts=ts, position_id=position_id)


def make_decision(action: str = "reject_cocoon", ts: float = NOW, mint: str = MINT_A) -> Decision:
    return Decision(ts=ts, mint=mint, action=action, reason="[top10] top-10 holders own 45.0% (max 30%)",
                    inputs={"top10_pct": 45.0}, symbol="HIGGS")


def tamper(db_path: Path, sql: str, params: tuple = ()) -> None:
    """Edit the database behind the ledger's back (what an attacker with file access could do)."""
    conn = sqlite3.connect(db_path)
    with conn:
        conn.execute(sql, params)
    conn.close()


def fill_chain(ledger: Ledger, n: int = 5) -> None:
    for i in range(1, n + 1):
        ledger.append_receipt("note", {"i": i, "msg": f"receipt {i}"}, ts=NOW + i)


# --------------------------------------------------------------------------- receipts


def test_empty_chain(ledger: Ledger) -> None:
    assert ledger.head() == (0, GENESIS_HASH)
    assert ledger.receipt_count() == 0
    assert ledger.receipts() == []
    assert ledger.verify_chain() == (True, None)


def test_receipt_hash_follows_the_published_formula(ledger: Ledger) -> None:
    first = ledger.append_receipt("boot", {"version": "0.1.0", "mode": "paper"}, ts=NOW + 0.12345)
    second = ledger.append_receipt("note", {"b": 2, "a": [1, 2.5, None]})
    assert (first.seq, second.seq) == (1, 2)
    assert first.ts == round(NOW + 0.12345, 3)
    assert first.prev_hash == GENESIS_HASH and second.prev_hash == first.hash
    # an independent re-implementation of docs/DESIGN.md section 5, without nightcrawler code
    body = json.dumps({"seq": 2, "ts": NOW, "kind": "note", "payload": {"a": [1, 2.5, None], "b": 2}},
                      sort_keys=True, separators=(",", ":"))
    assert second.hash == hashlib.sha256((first.hash + body).encode()).hexdigest()
    assert ledger.head() == (2, second.hash)
    assert ledger.receipts() == [first, second]


def test_payload_is_normalized_before_hashing_and_storing(db_path: Path, fake_clock: FakeClock) -> None:
    with Ledger(db_path, clock=fake_clock) as led:
        r = led.append_receipt("note", {"tuple": (1, 2), "path": Path("x"), "n": 7}, ts=1_791_475_200)
    assert r.payload == {"tuple": [1, 2], "path": "x", "n": 7}
    assert isinstance(r.ts, float)  # an int ts must hash identically after a round trip through REAL
    with Ledger(db_path, clock=fake_clock) as reopened:
        assert reopened.receipts() == [r]
        assert reopened.verify_chain() == (True, None)


def test_nan_payload_is_rejected_and_nothing_is_written(ledger: Ledger) -> None:
    with pytest.raises(ValueError):
        ledger.append_receipt("note", {"x": float("nan")})
    with pytest.raises(ValueError):
        ledger.record_decision(Decision(ts=NOW, mint=MINT_A, action="error", reason="x", inputs={"r": float("inf")}))
    assert ledger.receipt_count() == 0 and ledger.decisions() == []


@pytest.mark.parametrize(("sql", "params"), [
    ("UPDATE receipts SET payload = ? WHERE seq = 3", ('{"i":3,"msg":"receipt 3 (edited)"}',)),
    ("UPDATE receipts SET ts = ts + 60 WHERE seq = 3", ()),
    ("UPDATE receipts SET kind = 'fill' WHERE seq = 3", ()),
    ("UPDATE receipts SET hash = ? WHERE seq = 3", ("f" * 64,)),
    ("UPDATE receipts SET prev_hash = ? WHERE seq = 3", ("0" * 64,)),
    ("DELETE FROM receipts WHERE seq = 3", ()),
], ids=["payload", "ts", "kind", "hash", "prev_hash", "deleted"])
def test_any_tampering_is_detected_at_that_seq(ledger: Ledger, db_path: Path, sql: str, params: tuple) -> None:
    fill_chain(ledger, 5)
    assert ledger.verify_chain() == (True, None)
    tamper(db_path, sql, params)
    assert ledger.verify_chain() == (False, 3)


def test_rewriting_history_consistently_changes_the_head(ledger: Ledger, db_path: Path) -> None:
    """Even a forger who recomputes every later hash cannot keep a published head hash."""
    fill_chain(ledger, 4)
    published = ledger.head()
    prev = ledger.receipts()[1].hash
    for r in ledger.receipts(after_seq=2):
        payload = {**r.payload, "msg": "rewritten"} if r.seq == 3 else r.payload
        new_hash = receipt_hash(prev, r.seq, r.ts, r.kind, payload)
        tamper(db_path, "UPDATE receipts SET payload = ?, prev_hash = ?, hash = ? WHERE seq = ?",
               (json.dumps(payload, sort_keys=True, separators=(",", ":")), prev, new_hash, r.seq))
        prev = new_hash
    assert ledger.verify_chain() == (True, None)
    assert ledger.head()[0] == published[0] and ledger.head()[1] != published[1]


def test_export_jsonl_is_verifiable_without_nightcrawler(ledger: Ledger, tmp_path: Path) -> None:
    fill_chain(ledger, 3)
    ledger.record_decision(make_decision())
    out = tmp_path / "exports" / "receipts.jsonl"
    assert ledger.export_receipts(out) == 4
    lines = out.read_text(encoding="utf-8").splitlines()
    rows = [json.loads(line) for line in lines]
    assert [r["seq"] for r in rows] == [1, 2, 3, 4]
    assert set(rows[0]) == {"seq", "ts", "kind", "payload", "prev_hash", "hash", "body"}
    assert verify_receipts(rows) == (True, None)
    # the "~10 lines in any language" claim, done with hashlib + json only
    prev = "0" * 64
    for r in rows:
        body = json.dumps({k: r[k] for k in ("seq", "ts", "kind", "payload")}, sort_keys=True, separators=(",", ":"))
        assert r["prev_hash"] == prev
        prev = hashlib.sha256((prev + body).encode()).hexdigest()
        assert r["hash"] == prev
    assert prev == ledger.head()[1]
    assert not list(out.parent.glob("*.tmp"))


def test_iter_receipts_streams_long_chains_in_batches(ledger: Ledger) -> None:
    fill_chain(ledger, 7)
    assert [r.seq for r in ledger.iter_receipts(batch=3)] == list(range(1, 8))
    assert [r.seq for r in ledger.receipts(after_seq=2, limit=2)] == [3, 4]


def test_last_receipt_filters_by_kind_and_payload(ledger: Ledger) -> None:
    ledger.append_receipt("note", {"event": "paper_start", "start_lamports": 1})
    reset = ledger.append_receipt("note", {"event": "paper_reset", "start_lamports": 2})
    ledger.append_receipt("note", {"event": "other"})
    assert ledger.last_receipt("note", {"event": "paper_reset"}) == reset
    assert ledger.last_receipt("note").payload == {"event": "other"}
    assert ledger.last_receipt("halt") is None


# --------------------------------------------------------------------------- kv + transactions


def test_kv_roundtrip_upsert_and_resume_after_restart(db_path: Path, fake_clock: FakeClock) -> None:
    with Ledger(db_path, clock=fake_clock) as led:
        assert led.get_kv("paper.sol_lamports") is None
        assert led.get_kv("missing", default=7) == 7
        led.set_kv("paper.sol_lamports", 500_000_000)
        led.set_kv("paper.tokens", {MINT_A: 123})
        led.set_kv("paper.sol_lamports", 400_000_000)
    with Ledger(db_path, clock=fake_clock) as led:
        assert led.get_kv("paper.sol_lamports") == 400_000_000
        assert led.get_kv("paper.tokens") == {MINT_A: 123}


def test_transaction_rolls_back_everything_on_error(ledger: Ledger) -> None:
    ledger.set_kv("a", 1)
    with pytest.raises(RuntimeError), ledger.transaction():
        ledger.set_kv("a", 2)
        ledger.append_receipt("note", {"x": 1})
        ledger.record_fill(make_fill())
        raise RuntimeError("boom")
    assert ledger.get_kv("a") == 1
    assert ledger.head() == (0, GENESIS_HASH)
    assert ledger.fills() == []


def test_nested_transaction_is_a_savepoint(ledger: Ledger) -> None:
    with ledger.transaction():
        ledger.set_kv("outer", 1)
        with pytest.raises(KeyError), ledger.transaction():
            ledger.set_kv("inner", 1)
            raise KeyError("inner failure handled by the caller")
        ledger.append_receipt("note", {"after": True})
    assert ledger.get_kv("outer") == 1 and ledger.get_kv("inner") is None
    assert ledger.receipt_count() == 1


# --------------------------------------------------------------------------- records


def test_record_decision_is_receipted_atomically(ledger: Ledger, fake_clock: FakeClock) -> None:
    verdict = Verdict(decision="no", confidence=0.8, reasons=["insiders selling"], model="claude-opus-5-5",
                      latency_ms=900, cost_usd=0.002, source="claude")
    d1 = ledger.record_decision(make_decision())
    d2 = ledger.record_decision(Decision(ts=NOW + 5, mint=MINT_B, action="reject_judge", reason="judge said no",
                                         verdict=verdict))
    (r1, r2) = ledger.receipts()
    assert (d1.receipt_hash, d2.receipt_hash) == (r1.hash, r2.hash)
    assert r1.kind == "decision" and r1.ts == NOW
    assert r2.payload == {**d2.to_dict(), "receipt_hash": None}
    assert ledger.decisions() == [d2, d1]
    assert ledger.decisions(actions=["reject_cocoon"]) == [d1]
    assert ledger.decisions(limit=1)[0].verdict == verdict
    assert ledger.decision_counts() == {"reject_cocoon": 1, "reject_judge": 1}
    assert ledger.decision_counts(since=NOW + 1) == {"reject_judge": 1}


def test_record_fill_receipt_filters_and_duplicates(ledger: Ledger) -> None:
    buy = ledger.record_fill(make_fill("fill_1", ts=NOW))
    sell = ledger.record_fill(make_fill("fill_2", side="sell", ts=NOW + 60))
    other = ledger.record_fill(make_fill("fill_3", mint=MINT_B, ts=NOW + 120, position_id="pos_2"))
    receipts = ledger.receipts()
    assert [r.kind for r in receipts] == ["fill"] * 3
    assert buy.receipt_hash == receipts[0].hash and receipts[0].payload["receipt_hash"] is None
    assert receipts[0].payload == {**buy.to_dict(), "receipt_hash": None}
    assert ledger.fills() == [other, sell, buy]
    assert ledger.fills(limit=1) == [other]
    assert ledger.fills(mint=MINT_A) == [sell, buy]
    assert ledger.fills(since=NOW + 60) == [other, sell]
    assert ledger.fills(position_id="pos_1", limit=None) == [sell, buy]
    assert ledger.fills_after_seq(1) == [sell, other]
    assert ledger.fills_after_seq(0, mode="live") == []
    with pytest.raises(LedgerError, match="duplicate"):
        ledger.record_fill(make_fill("fill_1"))
    assert ledger.receipt_count() == 3


def test_swap_failure_receipt(ledger: Ledger) -> None:
    r = ledger.record_swap_failure({"outcome": "failed", "error": "slippage", "quote": {"in_amount": 1}})
    assert r.kind == "swap_failed" and r.ts == NOW and ledger.verify_chain() == (True, None)


def test_positions_upsert_and_queries(ledger: Ledger) -> None:
    p1 = Position(id="pos_1", mint=MINT_A, symbol="HIGGS", pool="pool", opened_at=NOW, token_decimals=6,
                  token_amount=5, cost_lamports=100)
    p2 = Position(id="pos_2", mint=MINT_B, symbol="HOOKI", pool=None, opened_at=NOW + 10, token_decimals=6)
    ledger.upsert_position(p2)
    ledger.upsert_position(p1)
    assert ledger.get_position("pos_1") == p1 and ledger.get_position("nope") is None
    assert [p.id for p in ledger.open_positions()] == ["pos_1", "pos_2"]
    assert ledger.last_closed_at(MINT_A) is None
    p1.status, p1.closed_at, p1.exit_reason, p1.token_amount = "closed", NOW + 300, "stop_loss", 0
    ledger.upsert_position(p1)
    assert [p.id for p in ledger.open_positions()] == ["pos_2"]
    assert [p.id for p in ledger.positions()] == ["pos_2", "pos_1"]
    assert ledger.positions(status="closed") == [p1]
    assert ledger.positions(limit=1)[0].id == "pos_2"
    assert ledger.last_closed_at(MINT_A) == NOW + 300


def test_equity_series_latest_and_curve(ledger: Ledger) -> None:
    assert ledger.latest_equity() is None and ledger.equity_curve() == []
    for i in range(1000):
        ledger.record_equity(EquityPoint(ts=NOW + 60 * i, equity_lamports=500_000_000 + i, sol_usd=200.0,
                                         equity_usd=100.0 + i / 100, mode="paper"))
    ledger.record_equity(EquityPoint(ts=NOW + 60 * 1000, equity_lamports=1, sol_usd=200.0, equity_usd=1.0,
                                     mode="live"))
    assert ledger.latest_equity().mode == "live"
    series = ledger.equity_series(since=NOW + 60 * 998)
    assert [p.equity_lamports for p in series] == [500_000_998, 500_000_999, 1]
    assert len(ledger.equity_series(limit=5)) == 5 and ledger.equity_series(limit=5)[0].ts == NOW
    curve = ledger.equity_curve(max_points=300, mode="paper")
    assert 2 <= len(curve) <= 300
    assert curve == sorted(curve)
    assert curve[-1] == (NOW + 60 * 999, 100.0 + 999 / 100)  # the newest point is always kept
    assert ledger.equity_curve(since=NOW + 60 * 995, mode="paper") == [
        (NOW + 60 * i, 100.0 + i / 100) for i in range(995, 1000)]
    assert ledger.equity_curve(mode="live") == [(NOW + 60 * 1000, 1.0)]


def test_safety_failures_use_each_mints_latest_report(ledger: Ledger) -> None:
    ledger.record_safety(SafetyReport(mint=MINT_A, passed=False, hard_fail_reasons=["[top10] 45%"], checked_at=NOW))
    ledger.record_safety(SafetyReport(mint=MINT_A, passed=True, checked_at=NOW + 10))
    ledger.record_safety(SafetyReport(mint=MINT_B, passed=False, checked_at=NOW + 20,
                                      hard_fail_reasons=["[mint_authority] not renounced", "[shield] x"]))
    assert ledger.safety_failures() == {MINT_B: ["[mint_authority] not renounced", "[shield] x"]}
    assert ledger.safety_failures(since=NOW + 30) == {}


def test_candidates_keep_first_seen(ledger: Ledger, fake_clock: FakeClock) -> None:
    ledger.record_candidate(TokenCandidate(mint=MINT_A, symbol="HIGGS", discovered_at=NOW - 100))
    fake_clock.advance(50)
    ledger.record_candidate(TokenCandidate(mint=MINT_A, symbol="HIGGS2"))
    ledger.record_candidate(TokenCandidate(mint=MINT_B, symbol="HOOKI"))
    assert ledger.candidate_count() == 2
    assert ledger.candidate_count(since=NOW - 50) == 1


# --------------------------------------------------------------------------- storage


def test_file_database_uses_wal_and_survives_restart(db_path: Path, fake_clock: FakeClock) -> None:
    with Ledger(db_path, clock=fake_clock) as led:
        fill_chain(led, 3)
        head = led.head()
    conn = sqlite3.connect(db_path)
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    conn.close()
    with Ledger(db_path, clock=fake_clock) as led:
        assert led.head() == head and led.verify_chain() == (True, None)


def test_memory_database_and_closed_ledger(fake_clock: FakeClock) -> None:
    led = Ledger(":memory:", clock=fake_clock)
    led.append_receipt("note", {})
    led.close()
    led.close()  # idempotent
    with pytest.raises(LedgerError, match="closed"):
        led.head()


@pytest.mark.parametrize("version", [3, 7])
def test_refuses_a_database_from_a_newer_version(db_path: Path, version: int) -> None:
    db_path.parent.mkdir(parents=True)
    conn = sqlite3.connect(db_path)
    conn.execute(f"PRAGMA user_version={version}")  # 2 is v1 + positions.wallet (see the v2 test below)
    conn.close()
    with pytest.raises(LedgerError, match="newer"):
        Ledger(db_path)


def test_the_ledger_stays_readable_by_older_builds(db_path: Path, fake_clock: FakeClock) -> None:
    """positions.wallet is a nullable column older builds read and write without trouble: the version
    stays 1, so a rollback to an earlier image still opens the ledger (and manages live positions)."""
    with Ledger(db_path, clock=fake_clock) as led:
        led.upsert_position(_pos("p_live", "live"))
        led.set_position_wallet("p_live", WALLET_A)
    conn = sqlite3.connect(db_path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION == 1
    conn.close()


def test_a_ledger_marked_v2_by_an_earlier_build_opens_and_is_marked_v1_again(db_path: Path,
                                                                             fake_clock: FakeClock) -> None:
    with Ledger(db_path, clock=fake_clock) as led:
        led.upsert_position(_pos("p_live", "live"))
        led.set_position_wallet("p_live", WALLET_A)
        fill_chain(led, 2)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA user_version=2")  # what the builds that bumped the version wrote
    conn.close()
    with Ledger(db_path, clock=fake_clock) as led:
        assert led.position_wallets() == {"p_live": WALLET_A} and led.verify_chain() == (True, None)
    conn = sqlite3.connect(db_path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
    conn.close()


def test_read_only_ledger_reads_but_never_creates_migrates_or_writes(db_path: Path, fake_clock: FakeClock) -> None:
    with pytest.raises(LedgerError):
        Ledger(db_path, read_only=True)
    assert not db_path.parent.exists()  # neither the folder nor the file was created
    with pytest.raises(LedgerError):
        Ledger(":memory:", read_only=True)
    with Ledger(db_path, clock=fake_clock) as writer:
        fill_chain(writer, 3)
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA user_version=1")  # an older schema: a reader must not migrate it
        conn.close()
        with Ledger(db_path, clock=fake_clock, read_only=True) as reader:
            assert reader.read_only and reader.head() == writer.head()
            assert reader.verify_chain() == (True, None)
            writer.append_receipt("note", {"later": True})
            assert reader.head() == writer.head()  # sees the writer's new rows
            for write in (lambda: reader.append_receipt("note", {}), lambda: reader.set_kv("k", 1)):
                with pytest.raises(LedgerError, match="readonly"):
                    write()
        conn = sqlite3.connect(db_path)
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
        conn.execute("PRAGMA user_version=2")  # marked v2 by the builds that briefly bumped it: still readable
        conn.close()
        with Ledger(db_path, clock=fake_clock, read_only=True) as reader:
            assert reader.head() == writer.head()
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA user_version=3")
        conn.close()
    with pytest.raises(LedgerError, match="newer"):
        Ledger(db_path, read_only=True)
    sqlite3.connect(db_path.parent / "empty.db").close()
    with pytest.raises(LedgerError, match="no schema"):
        Ledger(db_path.parent / "empty.db", read_only=True)


def test_unwritable_data_dir_explains_the_railway_fix(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    folder = tmp_path / "volume"
    (folder / "nightcrawler.db").mkdir(parents=True)  # a directory where the file should be: sqlite cannot open it
    monkeypatch.setattr("nightcrawler.ledger.os.access", lambda *_: False)
    with pytest.raises(LedgerError, match="RAILWAY_RUN_UID=0"):
        Ledger(folder / "nightcrawler.db")


def test_concurrent_writers_and_readers_never_fork_the_chain(db_path: Path) -> None:
    """Threads share one Ledger, and a second Ledger on the same file plays 'another process'."""
    clock = FakeClock(NOW)
    primary, secondary = Ledger(db_path, clock=clock), Ledger(db_path, clock=clock)
    errors: list[BaseException] = []

    def writer(led: Ledger, name: str) -> None:
        try:
            for i in range(40):
                with led.transaction():
                    led.set_kv(f"{name}.i", i)
                    led.append_receipt("note", {"writer": name, "i": i})
        except BaseException as exc:  # pragma: no cover - surfaced below
            errors.append(exc)

    def reader() -> None:
        try:
            for _ in range(40):
                seq, _hash = primary.head()
                assert len(primary.receipts()) >= seq
                primary.decisions()
                primary.equity_series()
        except BaseException as exc:  # pragma: no cover - surfaced below
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(primary, "a")),
               threading.Thread(target=writer, args=(primary, "b")),
               threading.Thread(target=writer, args=(secondary, "c")), threading.Thread(target=reader),
               threading.Thread(target=reader)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert not errors
    assert primary.receipt_count() == 120
    assert [r.seq for r in primary.receipts()] == list(range(1, 121))
    assert primary.verify_chain() == (True, None) == secondary.verify_chain()
    assert secondary.get_kv("a.i") == 39 and primary.get_kv("c.i") == 39
    primary.close()
    secondary.close()


# --------------------------------------------------------------------------- review fixes


def test_export_carries_the_exact_hashed_body_for_verifiers_in_any_language(ledger: Ledger, tmp_path: Path) -> None:
    """JS/Go re-serialize floats and unicode differently (100.0 -> 100, 1e-05, \\uXXXX, big ints):
    the exported ``body`` is the exact hashed text, so ``sha256(prev + body)`` needs no JSON re-encoding."""
    ledger.append_receipt("note", {"start_usd": 100.0, "x": 0.00001, "symbol": "\u732b\U0001f680",
                                   "amount": 12345678901234567890}, ts=NOW)
    ledger.append_receipt("note", {"i": 2}, ts=1_791_475_200.0)
    out = tmp_path / "r.jsonl"
    ledger.export_receipts(out)
    prev = "0" * 64
    for line in out.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        assert row["prev_hash"] == prev
        prev = hashlib.sha256((prev + row["body"]).encode()).hexdigest()
        assert row["hash"] == prev
        assert json.loads(row["body"]) == {k: row[k] for k in ("seq", "ts", "kind", "payload")}


def _pos(pid: str, mode: str | None, *, mint: str = MINT_A, fill_ids: list[str] | None = None,
         tokens: int = 5_000_000) -> Position:
    return Position(id=pid, mint=mint, symbol="HIGGS", pool=None, opened_at=NOW, token_decimals=6,
                    entry_fill_ids=fill_ids or [], token_amount=tokens, initial_token_amount=tokens, mode=mode)


def test_open_positions_can_be_filtered_by_trading_mode(ledger: Ledger) -> None:
    ledger.upsert_position(_pos("p_paper", "paper"))
    ledger.upsert_position(_pos("p_live", "live", mint=MINT_B))
    live_fill = dataclasses.replace(make_fill("fill_live", position_id="p_old"), mode="live")
    ledger.record_fill(live_fill)
    ledger.upsert_position(_pos("p_old", None, fill_ids=["fill_live"]))  # a row written before Position.mode
    assert [p.id for p in ledger.open_positions()] == ["p_paper", "p_live", "p_old"]
    assert [p.id for p in ledger.open_positions(mode="paper")] == ["p_paper"]
    assert [p.id for p in ledger.open_positions(mode="live")] == ["p_live", "p_old"]
    assert ledger.get_position("p_old").mode == "live"  # inferred from its entry fill
    assert {p.id for p in ledger.positions(mode="live")} == {"p_live", "p_old"}


def test_mark_position_never_resurrects_or_resizes_a_position(ledger: Ledger) -> None:
    ledger.upsert_position(_pos("p1", "paper"))
    stale = ledger.get_position("p1")
    closed = dataclasses.replace(stale, status="closed", token_amount=0, closed_at=NOW + 5, exit_fill_ids=["f9"])
    ledger.upsert_position(closed)  # another process sold it meanwhile
    assert ledger.mark_position("p1", peak_price_usd=2.0, last_price_usd=1.5, last_marked_at=NOW + 10) is False
    after = ledger.get_position("p1")
    assert after.status == "closed" and after.token_amount == 0 and after.last_price_usd is None
    ledger.upsert_position(_pos("p2", "paper"))
    assert ledger.mark_position("p2", peak_price_usd=2.0, last_price_usd=1.5, last_marked_at=NOW + 10) is True
    p2 = ledger.get_position("p2")
    assert (p2.peak_price_usd, p2.last_price_usd, p2.last_marked_at, p2.token_amount) == (2.0, 1.5, NOW + 10,
                                                                                        5_000_000)


def test_update_open_position_refuses_a_stale_copy(ledger: Ledger) -> None:
    ledger.upsert_position(_pos("p1", "paper"))
    mine = ledger.get_position("p1")
    other = dataclasses.replace(mine, token_amount=0, status="closed", closed_at=NOW + 1)
    ledger.upsert_position(other)
    mine.token_amount -= 1_000_000
    with pytest.raises(LedgerError, match="changed"):
        ledger.update_open_position(mine, expected_token_amount=5_000_000)
    assert ledger.get_position("p1").status == "closed"
    ledger.upsert_position(_pos("p2", "paper"))
    fresh = ledger.get_position("p2")
    fresh.token_amount -= 1_000_000
    ledger.update_open_position(fresh, expected_token_amount=5_000_000)
    assert ledger.get_position("p2").token_amount == 4_000_000


# --------------------------------------------------------------------------- wallet of live positions (F3)

WALLET_A = "WaLLetAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
WALLET_B = "WaLLetBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB"


def test_a_position_records_the_wallet_it_lives_in(ledger: Ledger) -> None:
    ledger.upsert_position(_pos("p_live", "live"))
    ledger.set_position_wallet("p_live", WALLET_A)
    ledger.upsert_position(_pos("p_paper", "paper", mint=MINT_B))
    assert ledger.position_wallets() == {"p_live": WALLET_A, "p_paper": None}
    moved = ledger.get_position("p_live")
    moved.token_amount -= 1
    ledger.update_open_position(moved, expected_token_amount=5_000_000)  # later writes keep the wallet
    ledger.upsert_position(dataclasses.replace(moved, status="closed", closed_at=NOW + 1))
    assert ledger.position_wallets(["p_live"]) == {"p_live": WALLET_A}
    assert ledger.position_wallets() == {"p_paper": None}  # default: open positions only
    ledger.set_position_wallet("p_paper", WALLET_B)
    assert ledger.position_wallets() == {"p_paper": WALLET_B}


def _as_schema_v1(db_path: Path, wallet_kv: str | None) -> None:
    """Turn a fresh ledger file into what nightcrawler <= schema v1 wrote (no ``wallet`` column)."""
    conn = sqlite3.connect(db_path)
    with conn:
        conn.execute("ALTER TABLE positions DROP COLUMN wallet")
        if wallet_kv is not None:
            conn.execute("INSERT INTO kv(key, value, updated_at) VALUES ('wallet.pubkey', ?, 0)",
                         (json.dumps(wallet_kv),))
        conn.execute("PRAGMA user_version=1")
    conn.close()


def test_a_schema_v1_ledger_gets_the_wallet_column_and_a_default_for_live_rows(db_path: Path,
                                                                              fake_clock: FakeClock) -> None:
    with Ledger(db_path, clock=fake_clock) as old:
        old.upsert_position(_pos("p_live", "live"))
        old.upsert_position(_pos("p_paper", "paper", mint=MINT_B))
        old.record_fill(dataclasses.replace(make_fill("fill_live", position_id="p_old"), mode="live"))
        old.upsert_position(_pos("p_old", None, fill_ids=["fill_live"]))  # mode inferred from its fill
    _as_schema_v1(db_path, wallet_kv=WALLET_A)  # the wallet the last live boot used

    with Ledger(db_path, clock=fake_clock) as migrated:
        assert migrated.position_wallets() == {"p_live": WALLET_A, "p_paper": None, "p_old": WALLET_A}
        assert migrated.verify_chain() == (True, None)
    conn = sqlite3.connect(db_path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION == 1  # older builds still open it
    conn.close()
    with Ledger(db_path, clock=fake_clock) as again:  # idempotent
        assert again.position_wallets()["p_live"] == WALLET_A


def test_a_schema_v1_ledger_without_a_known_wallet_leaves_live_rows_unknown(db_path: Path,
                                                                           fake_clock: FakeClock) -> None:
    with Ledger(db_path, clock=fake_clock) as old:
        old.upsert_position(_pos("p_live", "live"))
    _as_schema_v1(db_path, wallet_kv=None)
    with Ledger(db_path, clock=fake_clock) as migrated:
        assert migrated.position_wallets() == {"p_live": None}
