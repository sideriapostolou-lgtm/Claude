#!/usr/bin/env bash
# B1 for lab2 S1/D1 (B1_PLAN P4b), one command:
#   1. wait for any running P1/P2/P3 backfill to exit (polls its process; never kills it);
#   2. P1 discovery down to TRAIN's first hour (--since 2026-10-01, --until 2026-10-09: no hour outside every
#      split), repeated until every curve and B2 hour of that range is done; it consolidates at the end;
#   3. for each split in order (TRAIN, then VAL, then TEST): refresh FLOW/b1_select.json (research/lab2/b1_select.py),
#      run phase P4b for that split only (repeated until nothing is left), which consolidates b1_trades.parquet,
#      b1_coins.parquet and b1_manifest.json at its end, and log the split's coverage.
# Every query goes through research/flow/cryptohouse.py: the shared query log, flock and rolling-hour budget.
#
# Usage:   bash research/flow/run_b1.sh                  # nohup bash research/flow/run_b1.sh >/dev/null 2>&1 &
# Env:     MAX_PER_HOUR (default 90; 110 only if the owner raised the cap), SPLITS ("train val test"),
#          SKIP_DISCOVERY=1, SINCE (2026-10-01), UNTIL (2026-10-09), FLOW, PYTHON, MAX_TRIES (4),
#          WAIT_PATTERN (pgrep -f regex of the processes to wait for), POLL_S (60)
# Log:     $FLOW/run_b1.log (plus FLOW/backfill.log); progress: FLOW/b1_progress.json, FLOW/b1_manifest.json
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FLOW="${FLOW:-/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/flow}"
PY="${PYTHON:-python}"
PER_HOUR="${MAX_PER_HOUR:-90}"
SPLITS="${SPLITS:-train val test}"
SINCE="${SINCE:-2026-10-01}"
UNTIL="${UNTIL:-2026-10-09}"
MAX_TRIES="${MAX_TRIES:-4}"
WAIT_PATTERN="${WAIT_PATTERN:-backfill\.py --phase P[123]( |\$)}"
POLL_S="${POLL_S:-60}"
LOG="$FLOW/run_b1.log"
BF="$REPO/research/flow/backfill.py"

log() { echo "$(date -u '+%F %T') run_b1: $*" | tee -a "$LOG"; }

exec 9>"$FLOW/run_b1.lock"
if ! flock -n 9; then
  echo "run_b1.sh is already running (lock $FLOW/run_b1.lock)" >&2
  exit 1
fi

wait_for_backfill() {
  local pids
  while pids="$(pgrep -f "$WAIT_PATTERN")"; do
    log "waiting for running backfill ($(echo $pids | tr '\n' ' ')) to exit; polling every ${POLL_S} s"
    sleep "$POLL_S"
  done
}

cd "$REPO" || exit 1
log "start: FLOW=$FLOW splits=[$SPLITS] cap=${PER_HOUR}/h since=$SINCE until=$UNTIL"
wait_for_backfill

if [ "${SKIP_DISCOVERY:-0}" != "1" ]; then
  for try in $(seq 1 "$MAX_TRIES"); do
    if "$PY" "$BF" --check-discovery --since "$SINCE" --until "$UNTIL" --out "$FLOW" >/dev/null; then
      log "discovery complete for [$SINCE, $UNTIL)"
      break
    fi
    log "discovery run $try: P1 --since $SINCE --until $UNTIL"
    "$PY" "$BF" --phase P1 --since "$SINCE" --until "$UNTIL" --out "$FLOW" --max-per-hour "$PER_HOUR" \
      >>"$FLOW/run_b1.out" 2>&1 || log "P1 exited with $?"
  done
  if ! gaps="$("$PY" "$BF" --check-discovery --since "$SINCE" --until "$UNTIL" --out "$FLOW")"; then
    log "WARNING: discovery still has gaps after $MAX_TRIES runs: $gaps (B1 continues on what is usable)"
  fi
fi

for split in $SPLITS; do
  for try in $(seq 1 "$MAX_TRIES"); do
    "$PY" "$REPO/research/lab2/b1_select.py" --flow "$FLOW" >>"$FLOW/run_b1.out" 2>&1 \
      || { log "b1_select failed ($?)"; exit 2; }
    log "P4b $split, run $try"
    "$PY" "$BF" --phase P4b --splits "$split" --out "$FLOW" --max-per-hour "$PER_HOUR" \
      >>"$FLOW/run_b1.out" 2>&1 || log "P4b exited with $?"
    status="$("$PY" - "$FLOW" "$split" <<'EOF'
import json, sys
f, s = sys.argv[1], sys.argv[2]
try:
    p = json.load(open(f"{f}/b1_progress.json"))
except (OSError, ValueError):
    print("unknown"); sys.exit()
a = (p.get("after") or {}).get(s) or {}
try:
    m = json.load(open(f"{f}/b1_manifest.json"))["splits"].get(s) or {}
except (OSError, ValueError, KeyError):
    m = {}
print(("done" if p.get("finished") and not a.get("units_left") else "more"),
      f"fetched={a.get('fetched')}/{a.get('selected')} errors={a.get('errors')} units_left={a.get('units_left')}",
      f"complete={m.get('complete')}/{m.get('selected')} frac={m.get('frac')} gate_flagged={m.get('gate_flagged')}")
EOF
)"
    log "$split: $status"
    case "$status" in done*) break ;; esac
  done
done
log "finished. Check: python research/lab2/s1.py --stage status ; python research/lab2/d1.py --stage status"
