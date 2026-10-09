"""The learner job: ``nightcrawler learn run --incremental`` in its own process (docs/LEARNING.md §2, §11).

The engine's ``learn`` stage starts it every LEARN_INTERVAL_MIN (:func:`spawn_learner`); a person may run
it too. Replay is CPU-bound pure Python: in a thread it would hold the GIL and could delay a stop-loss,
so it never runs inside the engine. One run (:func:`run_job`):

1. takes the ``learner`` LEASE in learn.db (one learner at a time, S6; a lease older than
   :data:`LEASE_STALE_S` is taken over) and renews it every :data:`LEASE_RENEW_S`;
2. registers the seeds not registered yet (``seeds.json``, within the weekly allowance); a seed the
   Settings put outside a hard range is skipped and listed in ``seeds_rejected`` (the card shows it);
3. replays every JUDGED day (no open coin) that is not finished yet, oldest first, one transaction
   per (variant, coin) (:func:`~nightcrawler.learn.replay.replay_day`). A day is finished for the
   variants frozen before its newest coin under the current ``sim_hash`` (meta ``learner.days``), so
   a finished day is never read again until a new variant is frozen before its coins;
4. scores every variant (:func:`~nightcrawler.learn.replay.update_scoreboard`: the scoreboard rows
   and, once per UTC day, the ``scoreboard`` outbox row the engine receipts);
5. records the run in meta ``learner.last_run`` (``learner.last_ok`` when it finished everything) and
   releases the lease.

STOPS between coins - every finished coin is already committed - on SIGTERM/SIGINT (``"signal"``),
when its parent is no longer the engine that started it (``"parent gone"``), when its lease was taken
over (``"lease lost"``) or when its wall budget ``max_seconds`` is spent (``"time"``; that one still
scores, which is fast). Results reach the receipt chain only through the outbox (S2).

Started by the engine (``--parent-pid``), the CLI first calls :func:`apply_limits`: nice 19, at most
:data:`MEMORY_LIMIT_BYTES` of address space and ``max_seconds + 30`` s of CPU. The child gets NO
secrets: :func:`learner_env` passes only the settings it reads (data dir, learning settings, the
paper haircut and impact cap, the strategy anchor, the log level) and ``--env-file`` is
``/dev/null``. It runs the parent's own code (from a source tree, ``PYTHONPATH`` leads to it) and never
imports from its working directory (``python -P``).

OBSERVATION LAG (§3.2): day D is replayed with ``L_obs`` = p75 of the engine's ``lag`` samples taken
in the :data:`LAG_WINDOW_D` days before D (:func:`l_obs_for_day`; >= 500 samples, else 60 s). Those rows
were all written before D began, so the value - and the replay - is a function of the tape.
"""

from __future__ import annotations

import dataclasses
import hashlib
import logging
import math
import os
import site
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

import nightcrawler
from nightcrawler import backtest, costs, strategy
from nightcrawler.hashing import canonical_json
from nightcrawler.learn import replay
from nightcrawler.learn.store import LearnStore, db_path, learn_dir
from nightcrawler.learn.tape import DEFAULT_L_OBS_S, TapeReader, tape_day
from nightcrawler.learn.variants import register_seeds, rejected_seeds
from nightcrawler.models import StrategyParams

__all__ = [
    "INCREMENTAL_MAX_S",
    "LEASE_NAME",
    "LEASE_STALE_S",
    "LEASE_RENEW_S",
    "MEMORY_LIMIT_BYTES",
    "NICE",
    "CPU_SLACK_S",
    "LAG_WINDOW_D",
    "CHILD_SETTINGS",
    "JobConfig",
    "apply_limits",
    "l_obs_for_day",
    "run_job",
    "describe_run",
    "learner_env",
    "learner_command",
    "spawn_learner",
    "provenance",
]

log = logging.getLogger("nightcrawler.learn.job")

#: Wall budget of one incremental run (seconds); the engine terminates a learner that overruns it.
INCREMENTAL_MAX_S = 600.0
LEASE_NAME = "learner"
#: A lease not renewed for this long belongs to a dead learner and is taken over.
LEASE_STALE_S = 2 * INCREMENTAL_MAX_S
LEASE_RENEW_S = 60.0
MEMORY_LIMIT_BYTES = 1 << 30
NICE = 19
#: CPU seconds allowed beyond the wall budget before the kernel stops the learner (SIGXCPU).
CPU_SLACK_S = 30
#: The observation lag of a day comes from the ``lag`` samples of the week before it ...
LAG_WINDOW_D = 7
#: ... read from the partitions of that week and of coins first seen a few days earlier still.
LAG_PARTITION_SLACK_D = 3
DAYS_META = "learner.days"
#: Settings the learner child reads; everything else - every secret above all - stays in the engine.
CHILD_SETTINGS = ("data_dir", "learn_enabled", "learn_disk_cap_gb", "learn_interval_min", "paper_slippage_bps",
                  "max_price_impact_pct", "log_level", *StrategyParams.FIELDS_FROM_SETTINGS)
#: Process environment the child keeps (no application variable).
CHILD_OS_ENV = ("PATH", "LANG", "LC_ALL", "TZ", "HOME", "TMPDIR", "SYSTEMROOT", "PYTHONDONTWRITEBYTECODE",
                "PYTHONUNBUFFERED")
_HARD_STOPS = frozenset({"signal", "parent gone", "lease lost"})
_LEARN_DIR = Path(__file__).parent


@dataclass(frozen=True)
class JobConfig:
    """What one run needs: where the data is, the strategy anchor (for the seeds), the simulator settings."""

    data_dir: Path
    anchor: StrategyParams
    sim: replay.SimConfig = field(default_factory=replay.SimConfig)
    max_seconds: float = INCREMENTAL_MAX_S
    parent_pid: int | None = None

    @classmethod
    def from_settings(cls, settings: Any, **overrides: Any) -> "JobConfig":
        return cls(data_dir=Path(settings.data_dir), anchor=settings.strategy_params(),
                   sim=replay.SimConfig.from_settings(settings), **overrides)


# --------------------------------------------------------------------------- limits


def _lower(kind: int, soft: int, hard: int) -> None:
    import resource

    cur_soft, cur_hard = resource.getrlimit(kind)
    if cur_hard != resource.RLIM_INFINITY:
        hard = min(hard, cur_hard)
    resource.setrlimit(kind, (min(soft, hard), hard))


def apply_limits(max_seconds: float) -> dict[str, Any]:
    """Lower this process's priority and limits (see the module docstring). Returns what was applied;
    never raises (a platform without ``resource`` simply runs unlimited)."""
    applied: dict[str, Any] = {}
    try:
        applied["nice"] = os.nice(max(0, NICE - os.nice(0)))
    except OSError:
        pass
    try:
        import resource

        _lower(resource.RLIMIT_AS, MEMORY_LIMIT_BYTES, MEMORY_LIMIT_BYTES)
        applied["as_bytes"] = MEMORY_LIMIT_BYTES
        cpu = int(math.ceil(max_seconds)) + CPU_SLACK_S
        _lower(resource.RLIMIT_CPU, cpu, cpu + CPU_SLACK_S)
        applied["cpu_s"] = cpu
    except (ImportError, ValueError, OSError):
        pass
    return applied


def _usage() -> dict[str, Any]:
    try:
        import resource
    except ImportError:
        return {}
    ru = resource.getrusage(resource.RUSAGE_SELF)
    return {"cpu_s": round(ru.ru_utime + ru.ru_stime, 3), "max_rss_mb": round(ru.ru_maxrss / 1024, 1)}


# --------------------------------------------------------------------------- observation lag


def _day_start(day: str) -> float:
    return datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()


def l_obs_for_day(reader: TapeReader, day: str, default: float = DEFAULT_L_OBS_S) -> float:
    """``L_obs`` for replaying ``day``: p75 of the ``gt_lag_s`` samples with ``ts`` in the
    :data:`LAG_WINDOW_D` days before it (:func:`~nightcrawler.learn.replay.estimate_l_obs`)."""
    end = _day_start(day)
    start = end - LAG_WINDOW_D * 86400.0
    samples = []
    for back in range(1, LAG_WINDOW_D + LAG_PARTITION_SLACK_D + 1):
        for row in reader.rows(tape_day(end - back * 86400.0), "lag"):
            ts, lag = row.get("ts"), row.get("gt_lag_s")
            if isinstance(ts, (int, float)) and start <= ts < end and isinstance(lag, (int, float)):
                samples.append(float(lag))
    return replay.estimate_l_obs(samples, default)


# --------------------------------------------------------------------------- one run


class _Stopper:
    """Why the run must stop now (None: carry on). Sticky; renews the lease while it is asked."""

    def __init__(self, cfg: JobConfig, store: LearnStore, now: Callable[[], float],
                 monotonic: Callable[[], float], stop_event: threading.Event | None) -> None:
        self.cfg, self.store, self.now, self.monotonic = cfg, store, now, monotonic
        self.stop_event = stop_event
        self.started = self.renewed = monotonic()
        self.reason: str | None = None

    def hard(self) -> str | None:
        if self.reason in _HARD_STOPS:
            return self.reason
        if self.stop_event is not None and self.stop_event.is_set():
            self.reason = "signal"
        elif self.cfg.parent_pid is not None and os.getppid() != self.cfg.parent_pid:
            self.reason = "parent gone"
        elif self.monotonic() - self.renewed >= LEASE_RENEW_S:
            self.renewed = self.monotonic()
            if not self.store.acquire_lease(LEASE_NAME, os.getpid(), self.now(), LEASE_STALE_S):
                self.reason = "lease lost"
        return self.reason if self.reason in _HARD_STOPS else None

    def __call__(self) -> str | None:
        if self.hard() is None and self.monotonic() - self.started >= self.cfg.max_seconds:
            self.reason = "time"
        return self.reason


def _day_key(store: LearnStore, day: str) -> str | None:
    """What a finished day was replayed for: the variants frozen before its newest coin, and the code
    (sim_hash). None when no variant was frozen before any of its coins (nothing to replay)."""
    newest = store.newest_created(day)
    frozen = sorted(v["hash"] for v in store.variants()
                    if newest is not None and v["t0"] is not None and v["t0"] < newest)
    if not frozen:
        return None
    body = {"sim_hash": replay.sim_hash(), "variants": frozen}
    return hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()


def _replay_days(store: LearnStore, cfg: JobConfig, summary: dict[str, Any], stop: _Stopper,
                 now: Callable[[], float]) -> str | None:
    reader = TapeReader(learn_dir(cfg.data_dir) / "tape")
    done = dict(store.get_meta(DAYS_META, {}))
    for day in store.days():
        if stop():
            return stop.reason
        judged, complete, _ = replay.day_ready(store, day)
        key = _day_key(store, day) if judged else None
        if key is None or (done.get(day) or {}).get("key") == key:
            continue
        l_obs = l_obs_for_day(reader, day) if complete else DEFAULT_L_OBS_S
        sim = dataclasses.replace(cfg.sim, l_obs_s=l_obs)
        counts = replay.replay_day(store, reader, day, now(), sim, should_stop=lambda: stop() is not None)
        summary["days"][day], summary["l_obs_s"][day] = counts, l_obs
        if stop():
            return stop.reason
        done[day] = {"key": key, "l_obs_s": l_obs, "counts": counts, "at": now()}
        store.set_meta(DAYS_META, done)
    return None


def run_job(cfg: JobConfig, *, now: Callable[[], float] = time.time, stop_event: threading.Event | None = None,
            limits: Mapping[str, Any] | None = None,
            monotonic: Callable[[], float] = time.monotonic) -> dict[str, Any]:
    """One incremental learner run (see the module docstring). Returns its summary: ``status`` is ``ok``,
    ``stopped`` (``reason`` says why; progress is kept), ``busy`` (another learner holds the lease) or
    ``error`` (the exception is re-raised after the run is recorded)."""
    t_start = monotonic()
    started = now()
    summary: dict[str, Any] = {"status": "ok", "reason": None, "pid": os.getpid(), "started": started,
                               "finished": None, "registered": [], "seeds_rejected": [], "days": {}, "l_obs_s": {},
                               "scored": 0,
                               "limits": dict(limits) if limits is not None else None}
    with LearnStore(db_path(cfg.data_dir)) as store:
        if not store.acquire_lease(LEASE_NAME, os.getpid(), started, LEASE_STALE_S):
            summary.update(status="busy", reason="another learner holds the lease", finished=now())
            return summary
        stop = _Stopper(cfg, store, now, monotonic, stop_event)
        try:
            if stop.hard() is None:
                summary["registered"] = register_seeds(store, cfg.anchor, now())
                summary["seeds_rejected"] = rejected_seeds(cfg.anchor)
                _replay_days(store, cfg, summary, stop, now)
            if stop.hard() is None:
                summary["scored"] = len(replay.update_scoreboard(store, now(), cfg.sim))
            summary.update(status="stopped" if stop.reason else "ok", reason=stop.reason)
        except Exception as exc:
            summary.update(status="error", reason=type(exc).__name__)
            raise
        finally:
            summary.update(finished=now(), seconds=round(monotonic() - t_start, 3), **_usage())
            try:
                store.set_meta("learner.last_run", summary)
                if summary["status"] == "ok":
                    store.set_meta("learner.last_ok", summary["finished"])
                store.release_lease(LEASE_NAME, os.getpid())
            except Exception as exc:  # never hide the run's own error
                log.warning("learner_record_failed error=%s", type(exc).__name__)
    return summary


def describe_run(summary: Mapping[str, Any]) -> str:
    """One plain line for the log: ``learner ok in 3.2 s: replayed 1,186 coins on 1 day ...``."""
    if summary.get("status") == "busy":
        return "learner busy: another learner holds the lease, nothing done"
    coins = sum(sum(c.values()) for c in (summary.get("days") or {}).values())
    why = f" ({summary['reason']})" if summary.get("reason") else ""
    skipped = len(summary.get("seeds_rejected") or [])
    return (f"learner {summary.get('status')}{why} in {summary.get('seconds', 0.0):.1f} s: replayed {coins:,} "
            f"coins on {len(summary.get('days') or {})} day(s), scored {summary.get('scored', 0)} strategy "
            f"versions, registered {len(summary.get('registered') or [])}"
            + (f", skipped {skipped} seeds outside the learner's limits" if skipped else ""))


# --------------------------------------------------------------------------- the child process


def _env_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return repr(value)
    return str(value)


def _code_root() -> str | None:
    """The directory this code was imported from when it is a source tree (it then leads the child's
    ``PYTHONPATH``); None for an installed package, which the child finds by itself."""
    root = Path(nightcrawler.__file__).resolve().parents[1]
    installed = {Path(p).resolve() for p in (*site.getsitepackages(), site.getusersitepackages())}
    return None if root in installed else str(root)


def learner_env(settings: Any, base: Mapping[str, str] | None = None) -> dict[str, str]:
    """The child's whole environment: :data:`CHILD_OS_ENV` from ``base`` (default ``os.environ``), the
    :data:`CHILD_SETTINGS` values and, from a source tree, ``PYTHONPATH`` led by that tree (the child
    runs exactly this code, never another installed copy)."""
    base = os.environ if base is None else base
    env = {name: base[name] for name in CHILD_OS_ENV if base.get(name)}
    env.update({name.upper(): _env_value(getattr(settings, name)) for name in CHILD_SETTINGS})
    path = [p for p in (_code_root(), base.get("PYTHONPATH")) if p]
    if path:
        env["PYTHONPATH"] = os.pathsep.join(path)
    return env


def learner_command(parent_pid: int, max_seconds: float) -> list[str]:
    return [sys.executable, "-P", "-m", "nightcrawler", "--env-file", os.devnull, "learn", "run", "--incremental",
            "--parent-pid", str(int(parent_pid)), "--max-seconds", f"{max_seconds:g}"]


def spawn_learner(settings: Any, *, max_seconds: float = INCREMENTAL_MAX_S) -> subprocess.Popen:
    """Start one learner child of THIS process (it exits when this process is gone). Never waits for it."""
    return subprocess.Popen(learner_command(os.getpid(), max_seconds), env=learner_env(settings),
                            stdin=subprocess.DEVNULL, close_fds=True)


# --------------------------------------------------------------------------- provenance


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def provenance() -> dict[str, Any]:
    """``code_hashes`` (sha256 of ``strategy.py``, ``backtest.py``, ``costs.py`` and of the whole ``learn``
    package) and ``sim_hash``, for the engine's ``boot`` receipt (docs/LEARNING.md §8)."""
    digest = hashlib.sha256()
    for path in sorted(p for p in _LEARN_DIR.rglob("*") if p.suffix in (".py", ".json") and p.is_file()
                       and "__pycache__" not in p.parts):
        digest.update(path.relative_to(_LEARN_DIR).as_posix().encode("utf-8") + b"\0")
        digest.update(path.read_bytes() + b"\0")
    hashes = {name: _sha256(Path(cast(str, module.__file__))) for name, module in
              (("strategy", strategy), ("backtest", backtest), ("costs", costs))}
    return {"code_hashes": {**hashes, "learn": digest.hexdigest()}, "sim_hash": replay.sim_hash()}
