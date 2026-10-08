"""The recorder (docs/LEARNING.md §3.1, §10): census enrolment, an outcome-independent fetch schedule,
the candle and snapshot streams, the 429/403 circuit breaker, retries then ``incomplete``, hourly
segment roots, sealing, engine emits that never block, the low-disk pause, restart with backoff, and
zero learning calls with LEARN_ENABLED=false."""

from __future__ import annotations

import itertools
import threading
import time

import pytest

from fakes import FakeClock, FakeHttp, load_fixture
from nightcrawler.http import HttpClient
from nightcrawler.learn import recorder as rec_mod
from nightcrawler.learn.recorder import (
    CANDLE_FETCH_H,
    SNAP_AGES_MIN,
    Recorder,
    RecorderThread,
    build_http,
    start_recorder,
)
from nightcrawler.learn.store import LearnStore, learn_dir
from nightcrawler.learn.tape import MANIFEST, TapeReader, TapeWriter, tape_day, verify_segments
from nightcrawler.sources.pumpfun import CENSUS_HOST, HOST as SWAP_HOST

CENSUS_AT = 1_791_482_981.0  # 2026-10-08T18:09:41Z, when the lab captured the census fixture
CENSUS = "frontend-api-v3.pump.fun/coins"
CANDLES = "swap-api.pump.fun/v1/coins/"
DEXS = "api.dexscreener.com/tokens/v1/solana/"
ROWS = load_fixture("pumpfun_census_coins")
MINTS = sorted(r["mint"] for r in ROWS)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(CENSUS_AT)


@pytest.fixture
def world(tmp_path, clock):
    """A recorder over FakeHttp (no rate limits), its store and tape."""
    http_fake = FakeHttp()
    http_fake.register(CENSUS, ROWS)
    http_fake.register(CANDLES, load_fixture("pumpfun_candles_jet_1m"))
    http_fake.register(DEXS, lambda req: [{"chainId": "solana", "baseToken": {"address": m}, "priceUsd": "0.0001"}
                                          for m in req.url.rsplit("/", 1)[-1].split(",")])
    http = HttpClient(session=http_fake, clock=clock, rate_limits={}, default_rate=None, max_retries=0)
    store = LearnStore(tmp_path / "learn" / "learn.db")
    tape = TapeWriter(tmp_path / "learn" / "tape")
    recorder = Recorder(store, tape, http, clock=clock)
    yield recorder, http_fake, store
    recorder.close()


def run_for(recorder: Recorder, clock: FakeClock, hours: float, step_s: float = 600.0) -> None:
    end = clock.now() + hours * 3600
    while clock.now() < end:
        recorder.step()
        clock.advance(step_s)
    recorder.step()


# --------------------------------------------------------------------------- enrolment and schedule


def test_the_census_enrols_every_graduate_once_with_its_raw_row(world, clock) -> None:
    recorder, http, store = world
    recorder.step()
    assert sorted(c["mint"] for c in store.coins()) == MINTS
    assert [c.params["offset"] for c in http.calls_to(CENSUS)] == [0, 70, 140, *range(210, 981, 70)]  # sweep
    recorder.tape.flush()
    universe = TapeReader(recorder.tape.root).rows("2026-10-08", "universe")
    assert len(universe) == len(ROWS)  # the sweep saw them again: no second enrolment
    row = next(u for u in universe if u["mint"] == ROWS[0]["mint"])
    assert row["raw"] == ROWS[0] and row["ts"] == CENSUS_AT and row["created_ts"] == ROWS[0]["created_timestamp"] / 1000
    assert row["launch"]["symbol"] == ROWS[0]["symbol"] and row["src"]["pumpfun"] == [CENSUS_AT, 200]
    pmx = next(c for c in store.coins() if c["launch"]["symbol"] == "PMX")
    assert pmx["mayhem"] and not next(c for c in store.coins() if c["launch"]["symbol"] == "Taylor")["mayhem"]
    clock.advance(60)
    recorder.step()  # the census runs every 5 minutes, not every step
    assert len(http.calls_to(CENSUS)) == 15
    clock.advance(240)
    recorder.step()  # 5 minutes after the first pass: the top three pages again (the sweep is every 6 h)
    assert [c.params["offset"] for c in http.calls_to(CENSUS)][15:] == [0, 70, 140]


@pytest.mark.parametrize("candles", [[], "jet"])
def test_the_fetch_schedule_is_a_function_of_first_seen_only(world, clock, candles) -> None:
    """A dead coin and a trading coin get exactly the same fetches: skipping 'dead' coins would be an
    outcome-dependent choice."""
    recorder, http, store = world
    http.register(CANDLES, [] if candles == [] else load_fixture("pumpfun_candles_jet_1m"))
    recorder.step()
    for coin in store.coins():
        offsets = sorted((f["kind"], f["due_ts"] - coin["first_seen_ts"]) for f in store.fetches(coin["mint"]))
        assert offsets == sorted([("candles", h * 3600.0) for h in CANDLE_FETCH_H]
                                 + [("snaps", a * 60.0) for a in SNAP_AGES_MIN])
    run_for(recorder, clock, 51)
    assert len(http.calls_to(CANDLES)) == len(ROWS) * len(CANDLE_FETCH_H)
    for coin in store.coins():
        assert coin["status"] == "closed" and store.open_fetches(coin["mint"]) == 0  # the last fetch closes it
        assert coin["fetches_done"] == len(CANDLE_FETCH_H) + len(SNAP_AGES_MIN)


def test_the_candle_schedule_cannot_leave_a_hole_however_busy_the_coin_is() -> None:
    """pump.fun serves the newest 1000 TRADED minutes. If two fetches are more than ~1000 minutes apart, a
    coin that trades every minute gets a hole - only the busiest coins would lose their late candles, an
    outcome-dependent universe. Every gap of the fixed schedule is shorter than the page."""
    from nightcrawler.learn.tape import CANDLE_LIMIT

    gaps = [b - a for a, b in itertools.pairwise(CANDLE_FETCH_H)]
    assert all(gap * 60 + 1 < CANDLE_LIMIT for gap in gaps), gaps
    assert CANDLE_FETCH_H[0] == 3 and CANDLE_FETCH_H[-1] == 50


def test_a_coin_that_keeps_trading_is_covered_as_long_as_a_quiet_one() -> None:
    from learn_world import DAY0, record_coin
    from nightcrawler.learn.tape import TapeView
    from nightcrawler.models import Candle

    created = DAY0 + 3600

    def series(active_late: bool) -> list[Candle]:
        out = []
        for i in range(52 * 60):
            traded = i < 12 * 60 + 10 or active_late or i % 7 == 0
            out.append(Candle(int(created) + 60 * i, 3e-4, 3.003e-4, 2.997e-4, 3e-4, 100.0 if traded else 0.0))
        return out

    ends = []
    for active in (False, True):
        mint = ("HoleA" if active else "HoleQ") + "h" * 39
        rows = record_coin(mint, created, series(active), fetch_after_h=CANDLE_FETCH_H)
        view = TapeView(mint, DAY0 + 30 * 86400, rows)
        ends.append((view.covered_until, view.candles()[-1].ts))
    assert ends[0] == ends[1] and (ends[0][1] - created) / 3600 > 50


def test_candle_and_snapshot_rows_reach_the_tape(world, clock) -> None:
    recorder, http, store = world
    run_for(recorder, clock, CANDLE_FETCH_H[1] + 1)
    recorder.tape.flush()
    reader = TapeReader(recorder.tape.root)
    candles = reader.rows("2026-10-08", "candles")
    assert sorted({r["mint"] for r in candles}) == MINTS and len(candles) == 2 * len(ROWS)
    first = [r for r in candles if r["fetch"] == 1]
    assert all(r["rows"] and r["cover"][0] is None and r["src"]["pumpfun"][1] == 200 for r in first)
    second = [r for r in candles if r["fetch"] == 2]
    assert all(r["rows"] == [] for r in second)  # nothing new since: the same response, nothing stored twice
    snaps = reader.rows("2026-10-08", "snaps")
    assert sorted(s["age_min"] for s in snaps if s["mint"] == MINTS[0]) == sorted(SNAP_AGES_MIN)
    assert all(s["pair"]["baseToken"]["address"] == s["mint"] for s in snaps)
    assert len(http.calls_to(DEXS)) < len(snaps)  # batched: up to 30 mints per call


def live_bytes(store: LearnStore) -> int:
    store.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    pages = store.conn.execute("PRAGMA page_count").fetchone()[0] - store.conn.execute(
        "PRAGMA freelist_count").fetchone()[0]
    return pages * store.conn.execute("PRAGMA page_size").fetchone()[0]


def test_a_closed_coin_keeps_only_a_small_row_in_learn_db(world, clock) -> None:
    """learn.db must not grow with what the recorder needed BETWEEN fetches: once a coin closes its candle
    mark (the last 30 raw minutes) and its finished fetch rows are gone; the counts stay."""
    recorder, http, store = world
    empty = live_bytes(store)
    many = []
    for i in range(120):
        row = dict(ROWS[i % len(ROWS)])
        row["mint"] = f"Many{i:04d}" + ROWS[i % len(ROWS)]["mint"][8:]
        row["created_timestamp"] = ROWS[i % len(ROWS)]["created_timestamp"] - 1000 * i
        many.append(row)
    http.register(CENSUS, [])
    http.register(CENSUS, many, times=1)
    run_for(recorder, clock, CANDLE_FETCH_H[-1] + 8, step_s=300)  # 2 candle fetches a step: ~5 h per wave
    coins = store.coins()
    assert len(coins) == 120 and {c["status"] for c in coins} == {"closed"}
    assert all(c["mark"] is None and store.fetches(c["mint"]) == [] for c in coins)
    assert all(c["fetches_done"] == len(CANDLE_FETCH_H) + len(SNAP_AGES_MIN) for c in coins)
    assert store.summary()["fetches"] == {"pending": 0, "failed": 0,
                                          "done": 120 * (len(CANDLE_FETCH_H) + len(SNAP_AGES_MIN))}
    per_coin = (live_bytes(store) - empty) / 120
    assert per_coin < 1500, f"{per_coin:.0f} bytes of learn.db per closed coin"


# --------------------------------------------------------------------------- failures


def test_a_429_opens_the_circuit_breaker_for_that_host_only(world, clock) -> None:
    recorder, http, store = world
    http.register(CENSUS, "<html>Cloudflare</html>", status=429)
    recorder.step()
    assert len(http.calls_to(CENSUS)) == 1 and recorder.paused(CENSUS_HOST)
    assert store.coins() == []
    http.register(CENSUS, ROWS)
    clock.advance(rec_mod.BREAKER_S - 1)
    recorder.step()
    assert len(http.calls_to(CENSUS)) == 1  # nothing sent to a paused host
    clock.advance(1)
    recorder.step()
    assert len(http.calls_to(CENSUS)) > 1 and len(store.coins()) == len(ROWS)
    assert recorder.stats["breaker_trips"] == 1


def test_a_broken_census_page_waits_for_the_next_period_instead_of_hammering(world, clock) -> None:
    recorder, http, store = world
    http.register("coins?offset=140&", {"statusCode": 500}, status=500)
    recorder.step()  # the first pass is a sweep; it stops at the broken page
    assert [c.params["offset"] for c in http.calls_to(CENSUS)] == [0, 70, 140]
    http.register(CENSUS, ROWS)  # healthy again
    clock.advance(60)
    recorder.step()
    assert len(http.calls_to(CENSUS)) == 3  # no retry storm: next census in 5 minutes
    clock.advance(240)
    recorder.step()
    assert [c.params["offset"] for c in http.calls_to(CENSUS)][3:] == [0, 70, 140]  # top pages; the sweep waits 6 h
    assert recorder.stats["errors"] == 1 and len(store.coins()) == len(ROWS)


def test_a_rate_limited_fetch_is_postponed_without_counting_an_attempt(world, clock) -> None:
    recorder, http, store = world
    recorder.step()
    clock.advance(3 * 3600 + 1)
    http.register(CANDLES, {"error": "slow down"}, status=429, headers={"Retry-After": "30"})
    recorder.step()
    assert recorder.paused(SWAP_HOST) and len(http.calls_to(CANDLES)) == 1
    assert all(f["attempts"] == 0 for c in store.coins() for f in store.fetches(c["mint"]) if f["kind"] == "candles")


def test_five_failures_make_a_coin_incomplete(world, clock) -> None:
    recorder, http, store = world
    recorder.step()
    http.register(CANDLES, {"statusCode": 404}, status=404)
    run_for(recorder, clock, 4, step_s=300)
    assert all(c["status"] == "open" for c in store.coins())  # given up on +3 h, still waiting for +18 h
    assert not (recorder.tape.root / "2026-10-08" / MANIFEST).exists()
    run_for(recorder, clock, 50, step_s=300)  # past +50 h and its five tries
    for coin in store.coins():
        assert coin["status"] == "incomplete"
        assert [f["failed"] for f in store.fetches(coin["mint"]) if f["kind"] == "candles"] == [1] * len(CANDLE_FETCH_H)
        assert all(f["attempts"] == rec_mod.MAX_ATTEMPTS for f in store.fetches(coin["mint"]) if f["kind"] == "candles")


def test_a_host_that_refuses_for_good_ends_its_coins_incomplete_so_the_day_still_closes(world, clock,
                                                                                         make_settings) -> None:
    """A permanent 403 (e.g. Cloudflare blocking the server) never counts an attempt, so without a deadline
    the coins would stay open forever: no day judged or sealed. A fetch still not done GIVE_UP_AFTER_S after
    it was due is given up; the blocked host is recorded for the card."""
    from nightcrawler.learn.card import clear_cache, learning_card_state

    recorder, http, store = world
    http.register(CENSUS, [])
    http.register(CENSUS, ROWS, times=1)
    http.register(CANDLES, "<html>Attention Required! | Cloudflare</html>", status=403)
    run_for(recorder, clock, 10)
    blocked = store.get_meta("recorder.blocked")
    assert list(blocked) == [SWAP_HOST] and blocked[SWAP_HOST]["status"] == 403
    clear_cache()
    settings = make_settings(DATA_DIR=str(recorder.tape.root.parent.parent))
    warnings = learning_card_state(settings, clock.now())["warnings"]
    assert any("pump.fun candles" in w and "403" in w for w in warnings), warnings
    run_for(recorder, clock, CANDLE_FETCH_H[-1] + rec_mod.GIVE_UP_AFTER_S / 3600)
    assert {c["status"] for c in store.coins()} == {"incomplete"}
    assert (recorder.tape.root / "2026-10-08" / MANIFEST).exists()  # judged and sealed, files closed
    assert not [p for p in recorder.tape._files if p.parent.name == "2026-10-08"]
    http.register(CANDLES, [])  # the host answers again: no longer reported as blocked
    store.add_coin("Fresh" + MINTS[0][5:], created_ts=clock.now() - 600, first_seen_ts=clock.now(),
                   day=tape_day(clock.now()))
    store.schedule("Fresh" + MINTS[0][5:], "candles", clock.now())
    recorder.step()
    assert store.get_meta("recorder.blocked") == {}


# --------------------------------------------------------------------------- roots, seal


def test_hourly_segment_roots_go_to_the_outbox(world, clock) -> None:
    recorder, _, store = world
    recorder.step()
    roots = [o for o in store.outbox() if o["event"] == "tape_root"]
    assert len(roots) == 1 and verify_segments(recorder.tape.root, roots[0]["payload"]["segments"])
    clock.advance(1800)
    recorder.step()
    assert len([o for o in store.outbox() if o["event"] == "tape_root"]) == 1  # hourly
    clock.advance(1800)
    recorder.step()
    roots = [o for o in store.outbox() if o["event"] == "tape_root"]
    assert len(roots) == 2
    first_end = {s["file"]: s["end"] for s in roots[0]["payload"]["segments"]}
    for seg in roots[1]["payload"]["segments"]:  # each root covers only the bytes since the previous one
        assert seg["start"] == first_end.get(seg["file"], 0)
    assert verify_segments(recorder.tape.root, roots[1]["payload"]["segments"])


def test_a_finished_day_is_sealed_and_receipted_once(world, clock) -> None:
    recorder, http, store = world
    http.register(CENSUS, [])
    http.register(CENSUS, ROWS, times=1)  # one day of coins, then nothing new
    run_for(recorder, clock, 52)
    day = "2026-10-08"
    assert (recorder.tape.root / day / MANIFEST).exists()
    assert not list((recorder.tape.root / day).glob("*.jsonl"))
    seals = [o for o in store.outbox() if o["event"] == "tape_seal"]
    assert len(seals) == 1 and seals[0]["payload"]["day"] == day and seals[0]["payload"]["completeness"] == 1.0
    recorder.step()
    assert len([o for o in store.outbox() if o["event"] == "tape_seal"]) == 1
    assert len(TapeReader(recorder.tape.root).rows(day, "universe")) == len(ROWS)


def test_a_crash_after_the_seal_is_committed_still_deletes_the_raw_files(world, clock, monkeypatch) -> None:
    """The seal is committed (outbox row, sealed_days) before the raw .jsonl files are deleted; a crash in
    between must not leave them for ever: the next pass (or the next process) finishes the seal."""
    recorder, http, store = world
    http.register(CENSUS, [])
    http.register(CENSUS, ROWS, times=1)
    real = recorder.tape.finish_seal

    def crash(day: str) -> None:
        raise OSError("killed before the raw files were deleted")

    monkeypatch.setattr(recorder.tape, "finish_seal", crash)
    with pytest.raises(OSError):
        run_for(recorder, clock, CANDLE_FETCH_H[-1] + 2)
    day = "2026-10-08"
    assert day in store.get_meta("tape.sealed_days") and list((recorder.tape.root / day).glob("*.jsonl"))
    monkeypatch.setattr(recorder.tape, "finish_seal", real)
    recorder.step()  # the same process, next pass
    assert not list((recorder.tape.root / day).glob("*.jsonl"))
    assert len([o for o in store.outbox() if o["event"] == "tape_seal"]) == 1

    for path in (recorder.tape.root / day).glob("*.jsonl.gz"):  # the same crash, then a new process
        (recorder.tape.root / day / path.name[:-3]).write_bytes(b"{}\n")
    fresh = Recorder(store, TapeWriter(recorder.tape.root), recorder.http, clock=clock)
    fresh.step()
    assert not list((recorder.tape.root / day).glob("*.jsonl"))


# --------------------------------------------------------------------------- engine emits, disk


def test_engine_emits_never_block_and_are_drained_to_the_tape(world, clock) -> None:
    recorder, _, store = world
    small = Recorder(store, recorder.tape, recorder.http, clock=clock, emit_maxsize=2)
    row = {"v": 1, "ts": CENSUS_AT, "mint": "M", "kind": "enter"}
    assert small.emit("evals", row) and small.emit("evals", row)
    assert not small.emit("evals", row)  # full: dropped and counted, never waits
    assert small.stats["emits_dropped"] == 1
    small._drain_emits(CENSUS_AT)
    small.tape.flush()
    assert TapeReader(small.tape.root).rows("2026-10-08", "evals") == [row, row]


def test_learning_writes_pause_on_low_disk(world, clock, monkeypatch) -> None:
    recorder, http, store = world
    monkeypatch.setattr(rec_mod, "_free_bytes", lambda path: 512 * 1024 * 1024)
    assert recorder.step() == {"skipped": "low disk"}
    assert http.calls == [] and store.coins() == []


# --------------------------------------------------------------------------- the thread


class Boom:
    def __init__(self) -> None:
        self.calls = 0

    def step(self) -> None:
        self.calls += 1
        raise RuntimeError("recorder bug")

    def close(self) -> None:
        pass


def wait_for(predicate, timeout: float = 5.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def test_a_crashing_recorder_is_restarted_with_backoff_and_never_raises() -> None:
    boom = Boom()
    thread = RecorderThread(boom, interval_s=0.01, backoff_s=(0.01, 0.04))
    thread.start()
    try:
        assert wait_for(lambda: thread.crashes >= 4)
        assert thread.is_alive() and thread.last_error == "RuntimeError"
    finally:
        thread.stop()
    assert not thread.is_alive()


def test_recorder_crashes_never_change_an_engine_tick(make_settings, tmp_path) -> None:
    from nightcrawler.engine import build_app
    from world import make_world

    def trade(with_crashing_recorder: bool) -> tuple[list, list]:
        clock, fake = FakeClock(1_791_475_200.0), FakeHttp()
        make_world(fake, clock)
        http = HttpClient(session=fake, clock=clock, rate_limits={}, default_rate=None)
        settings = make_settings(DATA_DIR=str(tmp_path / f"run{int(with_crashing_recorder)}"))
        settings.ensure_data_dir()
        app = build_app(settings, clock, http=http)
        thread = RecorderThread(Boom(), interval_s=0.001, backoff_s=(0.001, 0.002))
        if with_crashing_recorder:
            thread.start()
        try:
            results = []
            for _ in range(4):
                results.append(app.engine.tick(clock.now()))
                clock.advance(60)
            if with_crashing_recorder:
                assert wait_for(lambda: thread.crashes >= 3)
            return results, [(d.action, d.mint, d.reason) for d in app.ledger.decisions(limit=100)]
        finally:
            thread.stop()
            app.ledger.close()

    assert trade(True) == trade(False)


def test_learn_enabled_false_makes_zero_learning_calls(make_settings, tmp_path) -> None:
    fake = FakeHttp()
    settings = make_settings(LEARN_ENABLED=False)
    assert start_recorder(settings, session=fake, clock=FakeClock(CENSUS_AT)) is None
    assert fake.calls == [] and not learn_dir(settings.data_dir).exists()


def test_an_unusable_learn_dir_never_raises_into_the_engine(make_settings) -> None:
    settings = make_settings()
    learn_dir(settings.data_dir).write_text("a file where the learn directory should be", encoding="utf-8")
    assert start_recorder(settings, session=FakeHttp(), clock=FakeClock(CENSUS_AT)) is None


def test_learn_enabled_starts_a_daemon_recorder(make_settings) -> None:
    fake = FakeHttp()
    fake.register(CENSUS, ROWS)
    fake.register(DEXS, [])
    fake.register(CANDLES, [])
    thread = start_recorder(make_settings(), session=fake, clock=FakeClock(CENSUS_AT), interval_s=0.01)
    try:
        assert thread is not None and thread.daemon and wait_for(lambda: fake.calls_to(CENSUS))
    finally:
        thread.stop()
    assert all("pump.fun" in c.url or "dexscreener" in c.url for c in fake.calls)


def test_the_recorders_own_client_is_capped_below_every_hosts_spare_capacity() -> None:
    http = build_http(session=FakeHttp(), clock=FakeClock(CENSUS_AT))
    limits = http.limiter.limits
    assert limits[CENSUS_HOST][0] * 60 <= 12 and limits[SWAP_HOST][0] * 60 <= 6
    assert limits["api.dexscreener.com"][0] * 60 <= 4 and http.max_retries == 0
    assert http is not build_http(session=FakeHttp(), clock=FakeClock(CENSUS_AT))  # never the engine's client
    assert threading.current_thread().name != "learn-recorder"
