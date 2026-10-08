"""The learner job (docs/LEARNING.md §2, §11): ``nightcrawler learn run --incremental`` - lease, seeds,
judged days replayed once with per-coin commits, the scoreboard, stop reasons (signal, time, parent
gone), the observation lag from the week before a day, a child process that gets no secrets and runs
nice'd under rlimits, and the code hashes for the boot receipt."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

import nightcrawler
from learn_world import DAY0, freeze, make_coins, write_day
from nightcrawler.config import Settings
from nightcrawler.learn import job
from nightcrawler.learn import replay as rp
from nightcrawler.learn.job import JobConfig, l_obs_for_day, learner_command, learner_env, run_job, spawn_learner
from nightcrawler.learn.store import LearnStore, db_path, learn_dir
from nightcrawler.learn.tape import TapeReader, TapeWriter, tape_day
from nightcrawler.learn.variants import load_seeds, make_spec
from nightcrawler.models import StrategyParams

ANCHOR = StrategyParams()
BENCHMARK = make_spec("dip_rebound", {}, ANCHOR)
T0 = DAY0 + 600.0
LATER = DAY0 + 5 * 86400.0  # every coin of DAY0 is closed by then


def config(data: Path, **kw) -> JobConfig:
    return JobConfig(data_dir=data, anchor=ANCHOR, **kw)


def at(ts: float):
    return lambda: ts


@pytest.fixture(scope="module")
def coins():
    return make_coins(8, seed=11, start=T0 + 60, fetch_after_h=(3, 9))


def a_judged_day(data: Path, coins) -> str:
    """DAY0 on the tape with every coin closed and the benchmark frozen before them (receipted at T0)."""
    with LearnStore(db_path(data)) as store:
        day = write_day(learn_dir(data) / "tape", store, coins)
        freeze(store, BENCHMARK, T0)
    return day


# --------------------------------------------------------------------------- one run


def test_a_first_run_registers_the_seeds_scores_and_queues_receipts(tmp_path) -> None:
    summary = run_job(config(tmp_path), now=at(LATER))
    assert summary["status"] == "ok" and summary["reason"] is None
    assert len(summary["registered"]) == len(load_seeds())
    with LearnStore(db_path(tmp_path)) as store:
        assert len(store.variants()) == len(load_seeds())
        events = [o["event"] for o in store.outbox()]
        assert events.count("register") == len(load_seeds()) and events.count("scoreboard") == 1
        assert {r["variant_hash"] for r in store.scoreboard(tape_day(LATER))} == {v["hash"] for v in store.variants()}
        run = store.get_meta("learner.last_run")
        assert run["status"] == "ok" and run["finished"] == LATER and store.get_meta("learner.last_ok") == LATER
        assert store.acquire_lease(job.LEASE_NAME, pid=-1, now=LATER, stale_s=1.0)  # it was released
        store.release_lease(job.LEASE_NAME, pid=-1)
    again = run_job(config(tmp_path), now=at(LATER + 60))
    assert again["status"] == "ok" and again["registered"] == []  # nothing registered twice


def test_a_judged_day_is_replayed_once_and_then_skipped(tmp_path, coins) -> None:
    day = a_judged_day(tmp_path, coins)
    first = run_job(config(tmp_path), now=at(LATER))
    assert first["status"] == "ok" and sum(first["days"][day].values()) == len(coins)
    with LearnStore(db_path(tmp_path)) as store:
        evidence = store.evidence(BENCHMARK.hash)
        assert evidence and store.get_meta("learner.days")[day]["l_obs_s"] == 60.0
    second = run_job(config(tmp_path), now=at(LATER + 1800))
    assert second["status"] == "ok" and second["days"] == {}  # finished: not even read again
    with LearnStore(db_path(tmp_path)) as store:
        assert store.evidence(BENCHMARK.hash) == evidence
        board = {r["variant_hash"]: r for r in store.scoreboard(tape_day(LATER))}
        assert board[BENCHMARK.hash]["n"] == len(evidence)


def test_a_day_is_replayed_again_for_a_variant_frozen_before_its_coins(tmp_path, coins) -> None:
    day = a_judged_day(tmp_path, coins)
    run_job(config(tmp_path), now=at(LATER))
    other = make_spec("dip_rebound", {"dip_pct": 0.6}, ANCHOR)
    with LearnStore(db_path(tmp_path)) as store:
        freeze(store, other, T0)  # (a test shortcut: frozen before the day's coins)
    rerun = run_job(config(tmp_path), now=at(LATER + 60))
    assert sum(rerun["days"][day].values()) == len(coins)  # only the new variant's coins
    late = make_spec("dip_rebound", {"dip_pct": 0.7}, ANCHOR)
    with LearnStore(db_path(tmp_path)) as store:
        freeze(store, late, LATER)  # frozen after every coin of the day: nothing to replay
    assert run_job(config(tmp_path), now=at(LATER + 120))["days"] == {}


def test_a_stopped_run_keeps_every_finished_coin_and_the_next_run_completes_the_day(tmp_path, coins,
                                                                                     monkeypatch) -> None:
    reference = tmp_path / "reference"
    day = a_judged_day(reference, coins)
    run_job(config(reference), now=at(LATER))

    stopped = tmp_path / "stopped"
    a_judged_day(stopped, coins)
    stop = threading.Event()
    real, calls = rp.replay_coin, []

    def replay_then_signal(*args, **kwargs):
        calls.append(1)
        if len(calls) == 3:
            stop.set()  # SIGTERM arrives while the third coin is being replayed
        return real(*args, **kwargs)

    monkeypatch.setattr(rp, "replay_coin", replay_then_signal)
    partial = run_job(config(stopped), now=at(LATER), stop_event=stop)
    monkeypatch.setattr(rp, "replay_coin", real)
    assert partial["status"] == "stopped" and partial["reason"] == "signal"
    with LearnStore(db_path(stopped)) as store:
        assert len(store.replayed(BENCHMARK.hash)) == 3  # committed coin by coin
        assert day not in (store.get_meta("learner.days") or {})
        assert store.get_meta("learner.last_ok") is None and store.outbox(pending=True)  # seeds still queued
    resumed = run_job(config(stopped), now=at(LATER))
    assert resumed["status"] == "ok" and sum(resumed["days"][day].values()) == len(coins) - 3
    with LearnStore(db_path(reference)) as ref, LearnStore(db_path(stopped)) as got:
        assert got.evidence(BENCHMARK.hash) == ref.evidence(BENCHMARK.hash)
        assert rp.evidence_root(got.evidence(BENCHMARK.hash)) == rp.evidence_root(ref.evidence(BENCHMARK.hash))


def test_a_run_out_of_time_still_scores_but_replays_nothing_more(tmp_path, coins) -> None:
    day = a_judged_day(tmp_path, coins)
    summary = run_job(config(tmp_path, max_seconds=0.0), now=at(LATER))
    assert summary["status"] == "stopped" and summary["reason"] == "time" and summary["days"] == {}
    with LearnStore(db_path(tmp_path)) as store:
        assert store.replayed(BENCHMARK.hash) == {} and store.scoreboard(tape_day(LATER))
        assert day not in (store.get_meta("learner.days") or {})


def test_a_learner_whose_engine_is_gone_stops_before_doing_anything(tmp_path, coins) -> None:
    a_judged_day(tmp_path, coins)
    summary = run_job(config(tmp_path, parent_pid=os.getppid() + 7919), now=at(LATER))
    assert summary["status"] == "stopped" and summary["reason"] == "parent gone"
    with LearnStore(db_path(tmp_path)) as store:
        assert store.replayed(BENCHMARK.hash) == {} and store.scoreboard(tape_day(LATER)) == []
        assert store.get_meta("learner.last_run")["reason"] == "parent gone"


def test_one_learner_at_a_time_and_a_stale_lease_is_taken_over(tmp_path) -> None:
    with LearnStore(db_path(tmp_path)) as store:
        assert store.acquire_lease(job.LEASE_NAME, pid=424242, now=LATER, stale_s=job.LEASE_STALE_S)
    busy = run_job(config(tmp_path), now=at(LATER + 10))
    assert busy["status"] == "busy" and busy["registered"] == []
    with LearnStore(db_path(tmp_path)) as store:
        assert store.variants() == []
    taken = run_job(config(tmp_path), now=at(LATER + job.LEASE_STALE_S + 1))
    assert taken["status"] == "ok" and taken["registered"]


# --------------------------------------------------------------------------- observation lag


def lag_rows(n: int, start: float, end: float, lag: float) -> list[dict]:
    step = (end - start) / n
    return [{"v": 1, "ts": start + i * step, "mint": None, "gt_lag_s": lag, "source": "geckoterminal"}
            for i in range(n)]


def test_the_observation_lag_of_a_day_comes_from_the_week_before_it_only(tmp_path) -> None:
    day, day_start = "2026-10-15", DAY0 + 7 * 86400.0
    with TapeWriter(tmp_path) as w:
        for row in lag_rows(300, day_start - 3 * 86400, day_start - 2 * 86400, 80.0):
            w.append("lag", tape_day(row["ts"]), row)
        for row in lag_rows(300, day_start - 86400, day_start - 1, 95.0):
            w.append("lag", tape_day(row["ts"]), row)
        for row in lag_rows(900, day_start, day_start + 3600, 5.0):  # from the day itself: never used
            w.append("lag", day, row)
        for row in lag_rows(900, day_start - 9 * 86400, day_start - 8 * 86400, 500.0):  # older than a week
            w.append("lag", tape_day(row["ts"]), row)
        w.append("lag", tape_day(day_start - 100), {"v": 1, "ts": day_start - 100, "sol_usd": 150.0})  # equity
    assert l_obs_for_day(TapeReader(tmp_path), day) == 95.0  # p75 of 300 x 80 s and 300 x 95 s
    assert l_obs_for_day(TapeReader(tmp_path), "2026-10-14") == 60.0  # < 500 samples before it: the default


def test_a_run_replays_a_day_with_its_own_observation_lag(tmp_path, coins) -> None:
    day = a_judged_day(tmp_path, coins)
    start = DAY0 * 1.0
    with TapeWriter(learn_dir(tmp_path) / "tape") as w:
        for row in lag_rows(600, start - 86400, start - 1, 140.0):
            w.append("lag", tape_day(row["ts"]), row)
    summary = run_job(config(tmp_path), now=at(LATER))
    assert summary["l_obs_s"] == {day: 140.0}
    with LearnStore(db_path(tmp_path)) as store:
        assert store.get_meta("learner.days")[day]["l_obs_s"] == 140.0


# --------------------------------------------------------------------------- the child process


SECRETS = {"ANTHROPIC_API_KEY": "sk-ant-api03-secretsecret0123", "DASHBOARD_TOKEN": "dash-token-secret-4567",
           "JUPITER_API_KEY": "jup-secret-key-89ab", "X_BEARER_TOKEN": "x-bearer-secret-cdef",
           "SOLANA_RPC_URL": "https://rpc.example.com/?api-key=rpc-secret-7777"}


def test_the_learner_child_gets_no_secret_and_only_the_settings_it_reads(make_settings) -> None:
    settings = make_settings(DIP_PCT=0.55, STOP_LOSS_PCT=0.25, PAPER_SLIPPAGE_BPS=150, MAX_PRICE_IMPACT_PCT=2.5,
                             LEARN_DISK_CAP_GB=2.0, LOG_LEVEL="DEBUG", **SECRETS)
    base = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "PYTHONPATH": "/somewhere/else", "TRADING_MODE": "live",
            "BOT_WALLET_SECRET": "wallet-secret-base58", "LIVE_CONFIRM": "I_ACCEPT_REAL_MONEY_RISK", **SECRETS}
    env = learner_env(settings, base=base)
    leaked = [*settings.secret_values(), "rpc-secret-7777", "wallet-secret-base58", *SECRETS.values()]
    assert not [s for s in leaked if any(s in value for value in env.values())]
    assert not {"TRADING_MODE", "LIVE_CONFIRM", "BOT_WALLET_SECRET", "SOLANA_RPC_URL", *SECRETS} & set(env)
    child = Settings.from_env(env)
    assert child.trading_mode == "paper" and child.secret_values() == []
    assert child.strategy_params() == settings.strategy_params() and child.data_dir == settings.data_dir
    assert (child.paper_slippage_bps, child.max_price_impact_pct, child.learn_disk_cap_gb, child.log_level) == (
        150, 2.5, 2.0, "DEBUG")
    assert env["PATH"] == "/usr/bin:/bin" and env["LANG"] == "C.UTF-8"
    root = str(Path(nightcrawler.__file__).resolve().parents[1])
    assert env["PYTHONPATH"].split(os.pathsep) == [root, "/somewhere/else"]  # the child runs THIS code


def test_an_installed_package_is_found_without_touching_pythonpath(make_settings, monkeypatch) -> None:
    monkeypatch.setattr(job, "_code_root", lambda: None)  # nightcrawler lives in site-packages (the Docker image)
    assert "PYTHONPATH" not in learner_env(make_settings(), base={"PATH": "/usr/bin"})
    assert learner_env(make_settings(), base={"PYTHONPATH": "/x"})["PYTHONPATH"] == "/x"


def test_the_learner_command_reads_no_env_file() -> None:
    cmd = learner_command(4321, 600.0)
    assert cmd[:4] == [sys.executable, "-P", "-m", "nightcrawler"]  # never imports from its working directory
    assert cmd[cmd.index("--env-file") + 1] == os.devnull and cmd.index("--env-file") < cmd.index("learn")
    assert cmd[cmd.index("learn"):cmd.index("learn") + 3] == ["learn", "run", "--incremental"]
    assert cmd[cmd.index("--parent-pid") + 1] == "4321" and cmd[cmd.index("--max-seconds") + 1] == "600"


def test_a_spawned_learner_runs_nice_and_limited_and_records_its_run(make_settings) -> None:
    settings = make_settings(**SECRETS)
    proc = spawn_learner(settings, max_seconds=120.0)
    assert proc.wait(timeout=120) == 0
    with LearnStore(db_path(settings.data_dir), readonly=True) as store:
        run = store.get_meta("learner.last_run")
        assert run["status"] == "ok" and run["pid"] == proc.pid
        assert run["limits"] == {"nice": 19, "as_bytes": job.MEMORY_LIMIT_BYTES, "cpu_s": 150}
        assert len(store.variants()) == len(load_seeds())


def test_sigterm_stops_a_spawned_learner_between_coins_within_seconds(make_settings) -> None:
    settings = make_settings()
    many = make_coins(40, seed=5, start=T0 + 60, spacing_s=600, fetch_after_h=(3, 9))
    a_judged_day(settings.data_dir, many)
    proc = spawn_learner(settings, max_seconds=120.0)
    try:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline and proc.poll() is None:
            with LearnStore(db_path(settings.data_dir), readonly=True) as store:
                if store.replayed(BENCHMARK.hash):
                    break
            time.sleep(0.05)
        proc.send_signal(signal.SIGTERM)  # what the engine forwards at shutdown
        sent = time.monotonic()
        assert proc.wait(timeout=10) == 0 and time.monotonic() - sent < 3.0
    finally:
        if proc.poll() is None:
            proc.kill()
    with LearnStore(db_path(settings.data_dir), readonly=True) as store:
        run = store.get_meta("learner.last_run")
        assert run["status"] == "stopped" and run["reason"] == "signal"
        assert 0 < len(store.replayed(BENCHMARK.hash)) < len(many)  # every finished coin kept, the rest left


def test_a_learner_started_by_someone_else_than_its_engine_exits_at_once(make_settings) -> None:
    settings = make_settings()
    done = subprocess.run(learner_command(os.getpid() + 7919, 60.0), env=learner_env(settings), timeout=120,
                          stdin=subprocess.DEVNULL, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    with LearnStore(db_path(settings.data_dir), readonly=True) as store:
        assert store.get_meta("learner.last_run")["reason"] == "parent gone" and store.variants() == []


# --------------------------------------------------------------------------- provenance


def test_provenance_hashes_the_code_behind_trading_and_learning() -> None:
    found = job.provenance()
    assert set(found["code_hashes"]) == {"strategy", "backtest", "costs", "learn"}
    assert all(len(h) == 64 for h in found["code_hashes"].values()) and found["sim_hash"] == rp.sim_hash()
    assert found == job.provenance()  # deterministic
