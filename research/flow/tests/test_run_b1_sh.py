"""run_b1.sh control flow with a fake interpreter: wait for the running backfill, discovery until complete, then
b1_select + P4b per split strictly in order (TRAIN, VAL, TEST), repeating a split until nothing is left."""
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "run_b1.sh"

FAKE = r"""#!/usr/bin/env bash
echo "$*" >> "$CALLS"
if [ "$1" = "-" ]; then exec "$REAL_PY" "$@"; fi
case "$*" in
  *--check-discovery*)
    n=$(grep -c -- '--check-discovery' "$CALLS"); [ "$n" -ge 3 ] && exit 0; echo '{"curve":["x"],"b2":[]}'; exit 1 ;;
  *"--phase P1"*) exit 0 ;;
  *b1_select.py*) exit 0 ;;
  *"--phase P4b"*)
    split=$(echo "$*" | sed -E 's/.*--splits ([a-z_]+).*/\1/')
    n=$(grep -c -- "--phase P4b --splits $split" "$CALLS")
    if [ "$split" = "val" ] && [ "$n" -lt 2 ]; then fin=false; left=3; else fin=true; left=0; fi
    printf '{"splits_order": ["%s"], "finished": %s, "after": {"%s": {"fetched": 5, "selected": 5, "errors": 0, "units_left": %s}}}' \
      "$split" "$fin" "$split" "$left" > "$FLOW/b1_progress.json"
    exit 0 ;;
esac
exit 0
"""


def test_run_b1_waits_then_discovery_then_splits_in_order(tmp_path):
    fake = tmp_path / "python"
    fake.write_text(FAKE)
    fake.chmod(0o755)
    calls = tmp_path / "calls.txt"
    flow = tmp_path / "flow"
    flow.mkdir()
    # a stand-in for the running P1: the script must wait for it
    blocker = subprocess.Popen(["bash", "-c", "exec -a fakebackfill_P1_running sleep 3"])
    env = dict(os.environ, PYTHON=str(fake), FLOW=str(flow), CALLS=str(calls), REAL_PY=sys.executable,
               WAIT_PATTERN="fakebackfill_P1_running", POLL_S="1", MAX_TRIES="4")
    t = time.time()
    r = subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=120)
    blocker.wait()
    assert r.returncode == 0, r.stderr
    assert time.time() - t >= 2.5, "did not wait for the running backfill"
    lines = calls.read_text().splitlines()
    kinds = []
    for ln in lines:
        if "--check-discovery" in ln:
            kinds.append("check")
        elif "--phase P1" in ln:
            kinds.append("P1")
            assert "--since 2026-10-01 --until 2026-10-09" in ln and "--max-per-hour 90" in ln
        elif "b1_select.py" in ln:
            kinds.append("select")
        elif "--phase P4b" in ln:
            kinds.append("P4b:" + ln.split("--splits ")[1].split()[0])
    assert kinds[:5] == ["check", "P1", "check", "P1", "check"]
    p4b = [k for k in kinds if k.startswith("P4b")]
    assert p4b == ["P4b:train", "P4b:val", "P4b:val", "P4b:test"]
    # b1_select runs before every P4b run (fresh selection after each consolidation)
    assert all(kinds[i - 1] == "select" for i, k in enumerate(kinds) if k.startswith("P4b"))
    log = (flow / "run_b1.log").read_text()
    assert "waiting for running backfill" in log and "discovery complete" in log and "finished" in log


def test_run_b1_refuses_a_second_instance(tmp_path):
    flow = tmp_path / "flow"
    flow.mkdir()
    import fcntl
    with open(flow / "run_b1.lock", "w") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        r = subprocess.run(["bash", str(SCRIPT)], env=dict(os.environ, FLOW=str(flow), PYTHON="false"),
                           capture_output=True, text=True, timeout=30)
    assert r.returncode == 1 and "already running" in r.stderr


# A P4b that dies before writing b1_progress.json (exception while loading, SIGKILL, OOM) must not be read as "done"
# from the previous split's file: TRAIN writes the real shape (finished, an "after" entry for EVERY selected split,
# units_left None for the splits it did not run), then VAL and TEST exit 1 without writing (B1-RUN-1).
FAKE_STALE = r"""#!/usr/bin/env bash
echo "$*" >> "$CALLS"
if [ "$1" = "-" ]; then exec "$REAL_PY" "$@"; fi
case "$*" in
  *"--phase P4b --splits train"*)
    printf '%s' '{"splits_order": ["train"], "dry_run": false, "finished": true, "after": {
      "train": {"selected": 5, "fetched": 5, "errors": 0, "todo": 0, "units_left": 0},
      "val": {"selected": 458, "fetched": 0, "errors": 0, "todo": 458, "units_left": null},
      "test": {"selected": 418, "fetched": 0, "errors": 0, "todo": 418, "units_left": null}}}' \
      > "$FLOW/b1_progress.json"
    exit 0 ;;
  *"--phase P4b"*) exit 1 ;;
esac
exit 0
"""


def test_run_b1_does_not_read_a_stale_progress_file_as_done(tmp_path):
    fake = tmp_path / "python"
    fake.write_text(FAKE_STALE)
    fake.chmod(0o755)
    calls = tmp_path / "calls.txt"
    flow = tmp_path / "flow"
    flow.mkdir()
    env = dict(os.environ, PYTHON=str(fake), FLOW=str(flow), CALLS=str(calls), REAL_PY=sys.executable,
               WAIT_PATTERN=_no_such_process(), POLL_S="1", MAX_TRIES="3", SKIP_DISCOVERY="1")
    r = subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=120)
    p4b = [ln.split("--splits ")[1].split()[0] for ln in calls.read_text().splitlines() if "--phase P4b" in ln]
    assert p4b == ["train"] + ["val"] * 3 + ["test"] * 3, p4b       # every try of VAL and TEST is used
    log = (flow / "run_b1.log").read_text()
    assert "train: done" in log
    assert "val: done" not in log and "test: done" not in log, log
    assert r.returncode != 0, "a run with splits not done must not exit 0"
    assert "NOT done" in log and "val" in log.split("NOT done")[-1] and "test" in log.split("NOT done")[-1]


@pytest.mark.parametrize("progress, expect", [
    ({"splits_order": ["val"], "finished": True, "after": {"val": {"units_left": 0}}}, "done"),
    ({"splits_order": ["train"], "finished": True, "after": {"val": {"units_left": 0}}}, "more"),     # other split
    ({"splits_order": ["val"], "finished": True, "after": {"val": {"units_left": None}}}, "more"),
    ({"splits_order": ["val"], "finished": False, "after": {"val": {"units_left": 0}}}, "more"),      # stopped
    ({"splits_order": ["val"], "finished": True, "after": {"val": {"units_left": 2}}}, "more"),
    ({"splits_order": ["val"], "finished": True, "after": {}}, "more"),
    (None, "more"),                                                                                 # no file
])
def test_run_b1_status_is_strict(tmp_path, progress, expect):
    """The status line reads 'done' only for a file written by a finished P4b run of exactly this split with an
    integer units_left == 0."""
    calls = tmp_path / "calls.txt"
    flow = tmp_path / "flow"
    flow.mkdir()
    body = "" if progress is None else json.dumps(progress).replace("'", "")
    fake = tmp_path / "python"
    fake.write_text(FAKE_STALE.replace(
        '  *"--phase P4b --splits train"*)', '  *"--phase P4b"*)\n'
        + (f"    printf '%s' '{body}' > \"$FLOW/b1_progress.json\"; exit 0 ;;\n" if body else "    exit 0 ;;\n")
        + '  *"--phase P4b --splits never"*)'))
    fake.chmod(0o755)
    env = dict(os.environ, PYTHON=str(fake), FLOW=str(flow), CALLS=str(calls), REAL_PY=sys.executable,
               WAIT_PATTERN=_no_such_process(), POLL_S="1", MAX_TRIES="1", SKIP_DISCOVERY="1", SPLITS="val")
    subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=60)
    status = [ln for ln in (flow / "run_b1.log").read_text().splitlines() if " run_b1: val: " in ln]
    assert len(status) == 1 and status[0].split(" run_b1: val: ")[1].startswith(expect), status


# Stopping run_b1.sh (kill / Ctrl-C) must stop its running child too and release run_b1.lock, so a restart (e.g. with
# another MAX_PER_HOUR) takes over at once; no child may inherit the lock fd (B1-RUN-2).
FAKE_SLOW = r"""#!/usr/bin/env bash
echo "$*" >> "$CALLS"
if [ "$1" = "-" ]; then exec "$REAL_PY" "$@"; fi
case "$*" in
  *"--phase P4b"*) exec -a "$CHILD_NAME" sleep 60 ;;
esac
exit 0
"""


def _no_such_process():
    """A wait pattern that matches no command line (built at run time, so not even this test's own source does)."""
    return "no_such_process_" + uuid.uuid4().hex


def _pids(name):
    r = subprocess.run(["pgrep", "-f", name], capture_output=True, text=True)
    return [int(x) for x in r.stdout.split()]


def test_stopping_run_b1_stops_the_child_and_frees_the_lock(tmp_path):
    import fcntl
    fake = tmp_path / "python"
    fake.write_text(FAKE_SLOW)
    fake.chmod(0o755)
    calls = tmp_path / "calls.txt"
    flow = tmp_path / "flow"
    flow.mkdir()
    name = f"fake_p4b_child_{os.getpid()}_{tmp_path.name}"
    env = dict(os.environ, PYTHON=str(fake), FLOW=str(flow), CALLS=str(calls), REAL_PY=sys.executable,
               WAIT_PATTERN=_no_such_process(), POLL_S="1", MAX_TRIES="1", SKIP_DISCOVERY="1",
               SPLITS="train", CHILD_NAME=name)
    proc = subprocess.Popen(["bash", str(SCRIPT)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        t = time.time()
        while not _pids(name) and time.time() - t < 30:
            time.sleep(0.1)
        assert _pids(name), "fake P4b child never started"
        proc.terminate()
        proc.wait(timeout=20)
        t = time.time()
        while _pids(name) and time.time() - t < 10:
            time.sleep(0.1)
        assert not _pids(name), "the P4b child outlived run_b1.sh"
        with open(flow / "run_b1.lock", "a") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)     # raises if an orphan still holds it
        assert "stopping" in (flow / "run_b1.log").read_text()
    finally:
        for pid in _pids(name):
            os.kill(pid, 9)
        if proc.poll() is None:
            proc.kill()


def test_no_child_inherits_the_run_b1_lock_fd(tmp_path):
    """Even after a kill -9 of run_b1.sh (no trap runs), an orphaned child must not keep run_b1.lock."""
    import fcntl
    import signal
    fake = tmp_path / "python"
    fake.write_text(FAKE_SLOW)
    fake.chmod(0o755)
    calls = tmp_path / "calls.txt"
    flow = tmp_path / "flow"
    flow.mkdir()
    name = f"fake_p4b_orphan_{os.getpid()}_{tmp_path.name}"
    env = dict(os.environ, PYTHON=str(fake), FLOW=str(flow), CALLS=str(calls), REAL_PY=sys.executable,
               WAIT_PATTERN=_no_such_process(), POLL_S="1", MAX_TRIES="1", SKIP_DISCOVERY="1",
               SPLITS="train", CHILD_NAME=name)
    proc = subprocess.Popen(["bash", str(SCRIPT)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        t = time.time()
        while not _pids(name) and time.time() - t < 30:
            time.sleep(0.1)
        assert _pids(name), "fake P4b child never started"
        proc.send_signal(signal.SIGKILL)
        proc.wait(timeout=20)
        with open(flow / "run_b1.lock", "a") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally:
        for pid in _pids(name):
            os.kill(pid, 9)
        if proc.poll() is None:
            proc.kill()
