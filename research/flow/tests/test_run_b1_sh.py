"""run_b1.sh control flow with a fake interpreter: wait for the running backfill, discovery until complete, then
b1_select + P4b per split strictly in order (TRAIN, VAL, TEST), repeating a split until nothing is left."""
import json
import os
import subprocess
import sys
import time
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
    printf '{"finished": %s, "after": {"%s": {"fetched": 5, "selected": 5, "errors": 0, "units_left": %s}}}' \
      "$fin" "$split" "$left" > "$FLOW/b1_progress.json"
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
