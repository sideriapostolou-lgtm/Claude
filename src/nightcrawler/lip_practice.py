"""The practice LIP desk's own process: pretend money on Kalshi's reward markets, read from the recorder's files.

PRACTICE ONLY, OFF BY DEFAULT. Nothing in this module, :mod:`nightcrawler.lip_desk`, :mod:`nightcrawler.lip_feed`
or :mod:`nightcrawler.lip_score` can place, cancel or amend an order: they hold no client, no key and no order path,
and they open no network connection at all (``tests/test_lip_practice.py`` checks the imports and names). The desk
only reads the public Kalshi recorder's segment files (docs/KALSHI_RECORDER.md) and writes its own small files.

Settings (its own variables, read from the environment; ``config.py``, real-money code, is untouched):

* ``KALSHI_LIP_PRACTICE_ENABLED`` (default ``false``): ``run`` does nothing without it, and the page shows "off".
* ``DATA_DIR`` (default ``./data``): it writes ``DATA_DIR/kalshi_lip_practice/`` (``panel.json``, ``state.json``,
  ``results/<UTC day>.jsonl``, older days gzipped, :data:`KEEP_DAYS` days kept).
* ``KALSHI_LIP_PRACTICE_RECORDER_DIR`` (default ``DATA_DIR/kalshi_recorder``): the recorder whose LIP books, prints,
  programs, market rows and Pyth prices it replays. The desk is useful only where that recorder writes (the
  ``kalshi-recorder`` service once it records the LIP lanes); where there is no recorder it idles and says so.

The process (the Kalshi arena's isolation, docs/COORDINATION.md "kalshi_arena contract"): ``run`` refuses to start
next to trading keys or a live switch (names only are checked; no value is read), then starts the desk in a child
Python process with an EMPTY environment (no key of any kind reaches it), isolated (``-I``), at the idle CPU class
and the lowest priority, first in line for the out-of-memory killer, under a 1 GiB memory limit, without core
dumps, and killed by the kernel if one pass hangs for :data:`HANG_S` or spends :data:`PASS_CPU_S` of CPU. The
child exits when its parent goes (the pipe closes), after a final save. A host process (the recorder, say) can start
the same child with :class:`LipPracticeLink`.

Commands::

    python -m nightcrawler.lip_practice run                     # needs KALSHI_LIP_PRACTICE_ENABLED=true
    python -m nightcrawler.lip_practice replay --recorder-dir DIR [--start ISO] [--end ISO] [--out FILE]
    python -m nightcrawler.lip_practice status [--data-dir DIR]
"""

from __future__ import annotations

import argparse
import contextlib
import gzip
import json
import logging
import math
import os
import signal
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .lip_desk import (
    ACCOUNTS,
    FILL_MODELS,
    POLICIES,
    LipDesk,
    replay,
    scorecard,
    scorecard_text,
)
from .lip_feed import (
    ALL_LANES,
    FX,
    LIP_LANES,
    RecorderTail,
    coverage_from_record,
    read_records,
)

PROGRAM_LANES = ("other", "lip")  # where the recorder writes GET /incentive_programs replies
EVENT_LANES = tuple(lane for lane in LIP_LANES if lane not in PROGRAM_LANES)
FACT_KINDS = frozenset({"incentives", "incentive_programs", "programs", "sweep", "discovery_markets", "settlement",
                        "markets", "market", "lip_markets"})

log = logging.getLogger("nightcrawler.lip_practice")

LABEL = "Practice (pretend money)"
PANEL_SCHEMA = 1
DIRNAME = "kalshi_lip_practice"
NOTE = ("Practice LIP desk: pretend money quoting Kalshi's reward markets on the recorder's public books, scored with "
        "the exact reward formula and the review's fill model. It has no order path; real money on LIP needs the "
        "playbook's go/no-go bar and the owner's word.")
POLL_S = 2.0  # how often the desk reads the recorder's new lines
DELAY_S = 15.0  # it plays events this far behind the clock (the recorder flushes every 5 s)
COVERAGE_WAIT_S = 300.0  # ... and waits at most this long for the print tape's coverage, then voids what it lacks
BACKLOG_S = 26 * 3600.0  # at a start it reads this much program history (programs are listed 8-24 h ahead)
EVENT_BACKLOG_S = 60.0  # ... and this much of the other lanes (a window open at the start is void anyway)
SAVE_EVERY_S = 60.0
STATUS_EVERY_S = 300.0
HALT_AFTER = 5
HANG_S = 120
PASS_CPU_S = 10.0
MEMORY_BYTES = 1 << 30
KEEP_DAYS = 60
PANEL_ROWS = 32  # newest day first, then FX, all, metals and gas, Coin Race (4 policies x 2 models a family)
PANEL_MAX_BYTES = 256 << 10
EXIT_UNSAFE = 3
EXIT_HALTED = 4
QUIET_S = 120.0  # no new recorder line for this long: the panel says the feed is quiet
# A copy of the bot's service carries these; the practice desk refuses to start next to them (names only).
TRADING_SECRET_NAMES = frozenset({"KALSHI_KEY_ID", "KALSHI_PRIVATE_KEY", "BOT_WALLET_SECRET"})
TRADING_SECRET_PREFIXES = ("POLYMARKET_US_",)


# ---------------------------------------------------------------------- settings
def _bool(raw: str) -> bool:
    value = raw.strip().lower()
    if value in ("1", "true", "yes", "on", "y"):
        return True
    if value in ("0", "false", "no", "off", "n", ""):
        return False
    raise ValueError("must be true or false")


@dataclass(frozen=True)
class LipPracticeSettings:
    enabled: bool
    data_dir: Path
    recorder_dir: Path

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> LipPracticeSettings:
        """The desk's own variables. A malformed switch reads as off (a practice desk never starts by mistake)."""
        try:
            enabled = _bool(env.get("KALSHI_LIP_PRACTICE_ENABLED", "false"))
        except ValueError:
            log.warning("kalshi_lip_practice_setting_invalid name=KALSHI_LIP_PRACTICE_ENABLED (read as off)")
            enabled = False
        data_dir = Path(env.get("DATA_DIR") or "./data")
        recorder = env.get("KALSHI_LIP_PRACTICE_RECORDER_DIR")
        return cls(enabled, data_dir, Path(recorder) if recorder else data_dir / "kalshi_recorder")

    @property
    def directory(self) -> Path:
        return self.data_dir / DIRNAME


def unsafe_names(env: Mapping[str, str]) -> list[str]:
    """Trading secrets or live switches present in ``env``: their NAMES only (no value is read)."""
    found = [name for name in env if name in TRADING_SECRET_NAMES or name.startswith(TRADING_SECRET_PREFIXES)]
    found += [name for name, value in env.items() if name.endswith("_MODE") and str(value).strip().lower() == "live"]
    return sorted(set(found))


# ---------------------------------------------------------------------- files
def _write(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _day(at: float) -> str:
    return datetime.fromtimestamp(at, UTC).date().isoformat()


class Results:
    """``results/<UTC day>.jsonl``: one line per window and resident (void windows once). A day's file is gzipped
    when the next day starts; :data:`KEEP_DAYS` days are kept."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory / "results"

    def append(self, rows: Sequence[Mapping[str, Any]]) -> None:
        if not rows:
            return
        self.directory.mkdir(parents=True, exist_ok=True)
        by_day: dict[str, list[str]] = {}
        for row in rows:
            by_day.setdefault(str(row.get("day")), []).append(json.dumps(dict(row), separators=(",", ":"),
                                                                         allow_nan=False))
        for day, lines in by_day.items():
            with (self.directory / f"{day}.jsonl").open("a", encoding="utf-8") as stream:
                stream.write("\n".join(lines) + "\n")

    def rotate(self, today: str) -> None:
        if not self.directory.is_dir():
            return
        for path in sorted(self.directory.glob("*.jsonl")):
            if path.stem < today:
                with path.open("rb") as source, gzip.open(path.with_suffix(".jsonl.gz"), "wb") as sink:
                    sink.write(source.read())
                path.unlink()
        cutoff = (datetime.fromisoformat(today) - timedelta(days=KEEP_DAYS)).date().isoformat()
        for path in self.directory.glob("*.jsonl*"):
            if path.name.split(".")[0] < cutoff:
                path.unlink()

    def read(self, days: Sequence[str]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for day in days:
            for path in (self.directory / f"{day}.jsonl", self.directory / f"{day}.jsonl.gz"):
                if not path.exists():
                    continue
                opener: Callable[..., Any] = gzip.open if path.suffix == ".gz" else open
                with opener(path, "rt", encoding="utf-8") as stream:
                    for line in stream:
                        with contextlib.suppress(ValueError):
                            row = json.loads(line)
                            if isinstance(row, dict):
                                out.append(row)
        return out


# ---------------------------------------------------------------------- the desk's process
class LipPractice:
    """The desk in its process: read the recorder's new lines, play them through :class:`LipDesk` behind the clock,
    write results, the panel and the state."""

    def __init__(self, data_dir: Path, recorder_dir: Path, *, clock: Callable[[], float] = time.time) -> None:
        self.clock = clock
        self.directory = Path(data_dir) / DIRNAME
        self.recorder_dir = Path(recorder_dir)
        now = clock()
        self.started_at = now
        self.desk = LipDesk(started_at=now)
        self.tails = (RecorderTail(self.recorder_dir, PROGRAM_LANES, start=now - BACKLOG_S),
                      RecorderTail(self.recorder_dir, EVENT_LANES, start=now - EVENT_BACKLOG_S))
        self.results = Results(self.directory)
        self.recent: list[dict[str, Any]] = []
        self.coverage_to: float | None = None
        self.coverage_seen_at: float | None = None
        self.last_record_at: float | None = None
        self.last_new_at: float | None = None
        self.lanes_seen: set[str] = set()
        self.problem: str | None = None
        self.errors = 0
        self.saved_at = -math.inf
        self.status_at = now
        self.hardening: dict[str, Any] | None = None
        self.uncovered: int | None = None  # the desk's gap entry for print coverage that is missing now
        self._restore(now)
        self.recent = [row for row in self.results.read([_day(now - 86_400), _day(now)])
                       if row.get("account") is None]

    # ------------------------------------------------------------------ state
    def _restore(self, now: float) -> None:
        path = self.directory / "state.json"
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except (OSError, ValueError):
            with contextlib.suppress(OSError):
                os.replace(path, path.with_name(f"state.json.bad-{int(now)}"))
            log.warning("kalshi_lip_practice_state_reset (unreadable; moved aside)")
            return
        saved = {row.get("account"): row for row in raw.get("accounts") or [] if isinstance(row, dict)}
        for account in self.desk.accounts:
            row = saved.get(account.name)
            if not isinstance(row, dict):
                continue
            with contextlib.suppress(KeyError, TypeError, ValueError):
                account.cash = {int(key): float(value) for key, value in row["cash"].items()}
                account.low = float(row["low_usd"])
                account.periods = int(row["periods"])
                account.reward = float(row["reward_usd"])
                account.contracts = float(row["contracts"])

    def state(self, now: float) -> dict[str, Any]:
        return {"version": 1, "label": LABEL, "saved_at": now, "started_at": self.started_at,
                "accounts": [{**account.row(), "cash": {str(key): value for key, value in account.cash.items()}}
                             for account in self.desk.accounts]}

    # ------------------------------------------------------------------ one pass
    def step(self, now: float) -> None:
        records = sorted((record for tail in self.tails for record in tail.poll()),
                         key=lambda row: (float(row.get("at") or 0.0), int(row.get("seq") or 0)))
        if records:
            self.last_new_at = now
        quoting: list[dict[str, Any]] = []
        before: list[dict[str, Any]] = []
        for record in records:
            lane = record.get("lane")
            if isinstance(lane, str):
                self.lanes_seen.add(lane)
            at = record.get("at")
            if isinstance(at, (int, float)):
                self.last_record_at = max(self.last_record_at or float(at), float(at))
            coverage = coverage_from_record(record)
            if coverage is not None and coverage.scope == "exchange":
                self.coverage_to = max(self.coverage_to or coverage.end, coverage.end)
                self.coverage_seen_at = now
            if isinstance(at, (int, float)) and float(at) < self.started_at and record.get("kind") not in FACT_KINDS:
                if record.get("kind") == "book":
                    before.append(record)  # history before the start: each market's newest book, never played
                continue
            quoting.append(record)
        self.desk.remember(before)
        self.desk.feed(quoting)
        mark = now - DELAY_S
        covered = self.coverage_to if self.coverage_to is not None else self.started_at  # none yet: nothing covered
        if covered < mark:
            if covered >= now - COVERAGE_WAIT_S:
                mark = covered  # wait for the print tape
            else:
                self._uncovered(covered, mark)  # it lags too long (or never came): what it lacks is void
        else:
            self.uncovered = None  # covered again: a later lapse is a new gap
        if mark > self.desk.watermark:
            rows = self.desk.advance(mark)
            self.results.append(rows)
            self.recent.extend(row for row in rows if row.get("account") is None)  # the accounts keep their own
        if now - self.saved_at >= SAVE_EVERY_S:
            self.save(now)
        if now - self.status_at >= STATUS_EVERY_S:
            self._status(now)

    def _uncovered(self, start: float, end: float) -> None:
        """Print coverage is missing from ``start``: one growing gap (not one per pass) voids what it touches."""
        if self.uncovered is None:
            self.desk.gaps.append((start, end))
            self.uncovered = len(self.desk.gaps) - 1
        else:
            first, _ = self.desk.gaps[self.uncovered]
            self.desk.gaps[self.uncovered] = (min(first, start), end)

    def save(self, now: float) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        today = _day(now)
        self.results.rotate(today)
        keep = {_day(now - 86_400), today}
        self.recent = [row for row in self.recent if row.get("day") in keep]
        _write(self.directory / "state.json", json.dumps(self.state(now), allow_nan=False, separators=(",", ":")))
        _write(self.directory / "panel.json", json.dumps(self.panel(now), allow_nan=False, separators=(",", ":")))
        self.saved_at = now

    def _status(self, now: float) -> None:
        self.status_at = now
        counters = self.desk.counters
        lag = None if self.last_record_at is None else round(now - self.last_record_at, 1)
        log.info("kalshi_lip_practice_status windows=%d settled=%d void=%d polls=%d prints=%d pyth=%d late=%d "
                 "lag_s=%s errors=%d (practice only)", counters.windows, counters.settled, counters.void,
                 counters.polls, counters.prints, counters.pyth, counters.late_records, lag, self.errors)

    # ------------------------------------------------------------------ the panel
    def panel(self, now: float) -> dict[str, Any]:
        days = {_day(now - 86_400), _day(now)}
        families = {FX: 0, "all": 1, "METAL_GAS": 2, "COINRACE": 3}
        policies = {policy.name: index for index, policy in enumerate(POLICIES)}
        # newest day first, FX first: the page shows the first 32 rows
        card = sorted((row for row in scorecard(self.recent) if row["day"] in days),
                      key=lambda row: (-int(row["day"].replace("-", "")), families.get(row["family"], 9),
                                       policies.get(row["policy"], 9), row["model"]))
        void: dict[str, int] = {}
        for row in self.recent:
            if row.get("void"):
                void[str(row["void"])] = void.get(str(row["void"]), 0) + 1
        counters = self.desk.counters
        pyth_live = sorted({window.series for window in self.desk.windows.values()
                            if window.pyth_last_at is not None and now - window.pyth_last_at <= 60.0})
        return {
            "schema_version": PANEL_SCHEMA, "mode": "paper", "label": LABEL, "as_of": now,
            "heartbeat_s": SAVE_EVERY_S, "problem": self.problem, "note": NOTE, "started_at": self.started_at,
            "policies": [{"name": policy.name, "place": policy.place, "size": policy.size, "stop_s": policy.stop_s,
                          "pyth_pull": policy.pyth_pull} for policy in POLICIES],
            "fill_models": list(FILL_MODELS), "primary_family": FX,
            "scorecard": card[:PANEL_ROWS],
            "accounts": [account.row() for account in self.desk.accounts],
            "windows": {"open": len(self.desk.windows), "settled": counters.settled, "void": counters.void,
                        "void_recent": dict(sorted(void.items()))},
            "feed": {"recorder_dir_found": self.recorder_dir.is_dir(), "last_record_at": self.last_record_at,
                     "last_new_at": self.last_new_at, "watermark": (None if not math.isfinite(self.desk.watermark)
                                                                    else self.desk.watermark),
                     "coverage_to": self.coverage_to, "records": counters.records, "polls": counters.polls,
                     "prints": counters.prints, "pyth": counters.pyth, "late": counters.late_records,
                     "lanes": sorted(self.lanes_seen), "pyth_live_series": pyth_live, "errors": self.errors,
                     "hardening": self.hardening},
        }


def panel_state(data_dir: Path | str) -> dict[str, Any]:
    """What the page shows, from ``panel.json`` only (never the larger files). The page builder runs in the live
    desk's process, so a file over :data:`PANEL_MAX_BYTES` is refused unread."""
    path = Path(data_dir) / DIRNAME / "panel.json"
    if path.stat().st_size > PANEL_MAX_BYTES:
        raise ValueError("LIP practice panel too large")
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or raw.get("label") != LABEL:
        raise ValueError("Invalid LIP practice panel")
    return raw


# ---------------------------------------------------------------------- isolation
def _harden() -> None:
    """Best effort, before any work: the idle CPU class and the lowest priority, first for the OOM killer, a memory
    limit, no core dump, Ctrl-C ignored (the desk follows its pipe). What took effect is read back by
    :func:`report_hardening`."""
    with contextlib.suppress(Exception):
        os.nice(19)
    with contextlib.suppress(Exception):
        os.sched_setscheduler(0, os.SCHED_IDLE, os.sched_param(0))
    with contextlib.suppress(Exception):
        Path("/proc/self/oom_score_adj").write_text("1000", encoding="ascii")
    with contextlib.suppress(Exception):
        import resource

        _soft, hard = resource.getrlimit(resource.RLIMIT_AS)
        if hard == resource.RLIM_INFINITY or hard > MEMORY_BYTES:
            resource.setrlimit(resource.RLIMIT_AS, (MEMORY_BYTES, hard))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    with contextlib.suppress(Exception):
        signal.signal(signal.SIGINT, signal.SIG_IGN)


def report_hardening() -> dict[str, Any]:
    def read(get: Callable[[], Any]) -> Any:
        try:
            return get()
        except Exception:  # noqa: BLE001 - unknown, shown as such
            return None

    import resource

    nice = read(lambda: int(os.getpriority(os.PRIO_PROCESS, 0)))
    policy = read(lambda: os.sched_getscheduler(0))
    idle = getattr(os, "SCHED_IDLE", None)
    sched = None if policy is None else "idle" if idle is not None and policy == idle else "other"
    soft = read(lambda: resource.getrlimit(resource.RLIMIT_AS)[0])
    limit = None if soft is None or soft == resource.RLIM_INFINITY else int(soft)
    oom = read(lambda: int(Path("/proc/self/oom_score_adj").read_text(encoding="ascii").strip()))
    report = {"nice": nice, "sched": sched, "as_limit_bytes": limit, "oom_score_adj": oom,
              "env_keys": sorted(os.environ),
              "applied": (nice is not None and nice >= 19 and sched == "idle" and limit is not None
                          and limit <= MEMORY_BYTES and oom == 1000)}
    log.info("kalshi_lip_practice_hardened nice=%s sched=%s as_limit=%s oom_score_adj=%s applied=%s env=%s", nice,
             sched, limit, oom, report["applied"], ",".join(report["env_keys"]))
    return report


def _alarm(seconds: int) -> None:
    """Two watchdogs re-armed before every pass (0 clears them); no handler, so the kernel ends a hung pass."""
    signal.alarm(seconds)
    signal.setitimer(signal.ITIMER_VIRTUAL, PASS_CPU_S if seconds else 0.0)


def worker_env() -> dict[str, str]:
    """The desk's whole environment: nothing from the deployment, so no key of any kind."""
    return {"PATH": os.defpath, "LANG": "C.UTF-8", "TZ": "UTC"}


def worker_command(data_dir: Path, recorder_dir: Path, fd: int) -> list[str]:
    """This interpreter, isolated, taking the idle class and the lowest priority BEFORE it imports this package."""
    root = str(Path(__file__).resolve().parent.parent)
    boot = ("import os, sys\n"
            "try:\n    os.sched_setscheduler(0, os.SCHED_IDLE, os.sched_param(0))\nexcept Exception:\n    pass\n"
            "try:\n    os.nice(19)\nexcept Exception:\n    pass\n"
            "sys.path.insert(0, sys.argv[1]); from nightcrawler.lip_practice import worker_main; "
            "sys.exit(worker_main())")
    return [sys.executable, "-I", "-X", "utf8", "-c", boot, root, str(data_dir), str(recorder_dir), str(fd)]


def serve(data_dir: Path, recorder_dir: Path, fd: int | None, *, clock: Callable[[], float] = time.time,
          sleep: Callable[[float], None] = time.sleep, alarm: Callable[[int], Any] = _alarm,
          hardening: Mapping[str, Any] | None = None, max_passes: int | None = None) -> int:
    """Run the desk until the parent's pipe closes (``fd``; None: forever or ``max_passes``): 0 after the final
    save, :data:`EXIT_HALTED` after :data:`HALT_AFTER` failed passes in a row."""
    practice = LipPractice(data_dir, recorder_dir, clock=clock)
    practice.hardening = None if hardening is None else dict(hardening)
    log.info("kalshi_lip_practice_started pid=%d recorder_dir_found=%s policies=%s accounts=%s (practice only, no "
             "order path)", os.getpid(), practice.recorder_dir.is_dir(), ",".join(p.name for p in POLICIES),
             ",".join(plan.name for plan in ACCOUNTS))
    if fd is not None:
        os.set_blocking(fd, False)
    failures = passes = 0
    while True:
        alarm(HANG_S)
        if fd is not None:
            try:
                if os.read(fd, 1 << 12) == b"":
                    break  # the parent is gone
            except BlockingIOError:
                pass
        try:
            practice.step(clock())
            failures = 0
        except Exception as exc:  # noqa: BLE001 - a practice desk halts itself; nothing else notices
            failures += 1
            practice.errors += 1
            log.warning("kalshi_lip_practice_step_failed error=%s", type(exc).__name__)
            if failures >= HALT_AFTER:
                practice.problem = "Practice LIP desk halted after repeated errors"
                with contextlib.suppress(Exception):
                    practice.save(clock())
                alarm(0)
                log.error("kalshi_lip_practice_halted error=%s", type(exc).__name__)
                return EXIT_HALTED
        passes += 1
        if max_passes is not None and passes >= max_passes:
            break
        sleep(POLL_S)
    alarm(0)
    with contextlib.suppress(Exception):
        practice.save(clock())
    log.info("kalshi_lip_practice_stopped settled=%d void=%d", practice.desk.counters.settled,
             practice.desk.counters.void)
    return 0


def worker_main() -> int:
    """The child's entry point (:func:`worker_command`): data dir, recorder dir and the parent's pipe in argv."""
    _harden()
    from .logging_setup import setup_logging

    setup_logging("INFO")
    data_dir, recorder_dir, fd = Path(sys.argv[-3]), Path(sys.argv[-2]), int(sys.argv[-1])
    return serve(data_dir, recorder_dir, fd, hardening=report_hardening())


class LipPracticeLink:
    """A host's handle on the desk's child process. :meth:`start` and :meth:`close` never raise and never block for
    long; the child exits on its own when the pipe closes (also when the host dies)."""

    def __init__(self, settings: LipPracticeSettings, *, command: Sequence[str] | None = None) -> None:
        self.settings = settings
        self.command = None if command is None else list(command)
        self.proc: subprocess.Popen[bytes] | None = None
        self.write_fd: int | None = None

    def start(self) -> bool:
        if self.proc is not None:
            return True
        if not self.settings.enabled:
            log.info("kalshi_lip_practice_off (KALSHI_LIP_PRACTICE_ENABLED is not true)")
            return False
        try:
            self.settings.directory.mkdir(parents=True, exist_ok=True)
            read_fd, write_fd = os.pipe()
            try:
                command = self.command if self.command is not None else worker_command(
                    self.settings.data_dir, self.settings.recorder_dir, read_fd)
                self.proc = subprocess.Popen(command, stdin=subprocess.DEVNULL, env=worker_env(),
                                             cwd=str(self.settings.directory), close_fds=True, pass_fds=(read_fd,),
                                             start_new_session=True)
            finally:
                os.close(read_fd)
            self.write_fd = write_fd
            log.info("kalshi_lip_practice_spawned pid=%d (its own process, empty environment, practice only)",
                     self.proc.pid)
            return True
        except Exception as exc:  # noqa: BLE001 - a practice desk never stops its host
            log.warning("kalshi_lip_practice_not_started error=%s", type(exc).__name__)
            self.close()
            return False

    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def close(self, wait_s: float = 0.0) -> None:
        if self.write_fd is not None:
            with contextlib.suppress(OSError):
                os.close(self.write_fd)
            self.write_fd = None
        if self.proc is not None and wait_s > 0:
            with contextlib.suppress(Exception):
                self.proc.wait(timeout=wait_s)


# ---------------------------------------------------------------------- commands
def _iso(text: str | None) -> float:
    """Epoch seconds from an ISO time (UTC when it names no zone); None or empty: the end of time."""
    if not text:
        return math.inf
    value = datetime.fromisoformat(text)
    return (value if value.tzinfo is not None else value.replace(tzinfo=UTC)).timestamp()


def _run(args: argparse.Namespace) -> int:
    settings = LipPracticeSettings.from_env(os.environ)
    if args.data_dir:
        settings = LipPracticeSettings(settings.enabled, Path(args.data_dir), Path(args.recorder_dir)
                                       if args.recorder_dir else Path(args.data_dir) / "kalshi_recorder")
    elif args.recorder_dir:
        settings = LipPracticeSettings(settings.enabled, settings.data_dir, Path(args.recorder_dir))
    unsafe = unsafe_names(os.environ)
    if unsafe:
        log.error("kalshi_lip_practice_refused names=%s (trading keys or a live switch present; the practice desk "
                  "runs only where none is)", ",".join(unsafe))
        return EXIT_UNSAFE
    if not settings.enabled:
        log.info("kalshi_lip_practice_off (set KALSHI_LIP_PRACTICE_ENABLED=true to run it)")
        return 0
    link = LipPracticeLink(settings)
    if not link.start():
        return 1
    stop = {"now": False}

    def on_term(_signum: int, _frame: Any) -> None:
        stop["now"] = True

    signal.signal(signal.SIGTERM, on_term)
    signal.signal(signal.SIGINT, on_term)
    while not stop["now"] and link.running():
        time.sleep(1.0)
    code = link.proc.poll() if link.proc is not None else None
    link.close(wait_s=10.0)
    return 0 if code in (None, 0) else int(code)


def _replay(args: argparse.Namespace) -> int:
    start, end = _iso(args.start) if args.start else -math.inf, _iso(args.end)
    records = read_records(Path(args.recorder_dir), ALL_LANES if args.all_lanes else LIP_LANES,
                           start=start - BACKLOG_S, end=end, verify=not args.no_verify)
    desk, rows = replay(records)
    card = scorecard(rows)
    print(scorecard_text(card, args.family))
    for account in desk.accounts:
        row = account.row()
        print(f"{row['account']:<22} start ${row['start_usd']:.2f} now ${row['equity_usd']:.2f} "
              f"low ${row['low_usd']:.2f} periods {row['periods']} reward ${row['reward_usd']:.2f}")
    print(f"windows {desk.counters.windows} settled {desk.counters.settled} void {desk.counters.void}; "
          "pretend money only")
    if args.out:
        Path(args.out).write_text(json.dumps({"scorecard": card, "accounts": [a.row() for a in desk.accounts],
                                              "rows": rows}, allow_nan=False), encoding="utf-8")
    return 0


def _status(args: argparse.Namespace) -> int:
    settings = LipPracticeSettings.from_env(os.environ)
    data_dir = Path(args.data_dir) if args.data_dir else settings.data_dir
    try:
        panel = panel_state(data_dir)
    except FileNotFoundError:
        print("no panel yet (the practice LIP desk has not saved; is KALSHI_LIP_PRACTICE_ENABLED true?)")
        return 1
    print(json.dumps({key: panel.get(key) for key in ("as_of", "problem", "windows", "feed", "accounts")}, indent=1))
    print(scorecard_text(panel.get("scorecard") or []))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m nightcrawler.lip_practice",
                                     description="The practice LIP desk (pretend money; no order path).")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="run the desk in its own isolated process (needs KALSHI_LIP_PRACTICE_ENABLED)")
    run.add_argument("--data-dir")
    run.add_argument("--recorder-dir")
    rep = sub.add_parser("replay", help="replay recorded files and print the scorecard")
    rep.add_argument("--recorder-dir", required=True)
    rep.add_argument("--start")
    rep.add_argument("--end")
    rep.add_argument("--family", default=FX)
    rep.add_argument("--out")
    rep.add_argument("--no-verify", action="store_true", help="skip the segment hash check")
    rep.add_argument("--all-lanes", action="store_true",
                     help="also read Family A's lanes (a recording made before the recorder had its LIP lanes)")
    status = sub.add_parser("status", help="print the saved panel")
    status.add_argument("--data-dir")
    args = parser.parse_args(argv)
    from .logging_setup import setup_logging

    setup_logging("INFO")
    return {"run": _run, "replay": _replay, "status": _status}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
