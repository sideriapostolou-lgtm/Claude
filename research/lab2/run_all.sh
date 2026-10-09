#!/usr/bin/env bash
# research/lab2/run_all.sh -- run every lab2 hypothesis module's TRAIN stage, then its VAL stage, and append one
# result row per (module, stage) to research/lab2/RUN_ALL.md.
#
# Modules are DISCOVERED by glob, never listed by hand: g1 m1 s1 d1, then x*.py, y*.py and z*.py in research/lab2/
# (version order: x2 before x10). A file counts as a hypothesis module only when it has the stage CLI (a module-level
# STAGES tuple, a main() and a --stage argument), so helpers such as common.py or b1_select.py are never run. A new
# designer's x7.py / y6.py / z6.py is picked up without editing this script.
#
# It NEVER runs TEST, CONFIRM or FINAL: the only stages it passes are train and val, and it removes the judge's flags
# (LAB2_ALLOW_TEST, LAB2_ALLOW_CONFIRM, LAB2_ALLOW_FINAL) from every child's environment. Those looks are spent one
# hypothesis at a time, by hand, with the flag set.
#
# Each module enforces its own prerequisites: a stage that may not run exits 2 ("REFUSED ...") and is recorded as a
# row; the run continues with the next stage / module. VAL is attempted after every TRAIN (the module refuses it
# unless an official TRAIN wrote a shortlist), so a second invocation picks up modules whose TRAIN ran earlier.
#
# Usage:
#   research/lab2/run_all.sh                    # every discovered module: --stage train, then --stage val
#   research/lab2/run_all.sh y1 x5              # only these modules (each must be a discovered module)
#   research/lab2/run_all.sh --list             # print the discovered modules and exit
#   RUN_ALL_TRAIN_ARGS=--allow-partial research/lab2/run_all.sh    # provisional TRAIN (never unlocks VAL)
#   RUN_ALL_STAGES=train research/lab2/run_all.sh                  # TRAIN only (any subset of: train val)
#
# Env: PYTHON (default python3); RUN_ALL_TIMEOUT seconds per stage (default 7200); RUN_ALL_MD (default
# research/lab2/RUN_ALL.md); RUN_ALL_LOG_DIR (default ${TMPDIR:-/tmp}/lab2_run_all/<run id>: full output per stage).
set -u

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
PY="${PYTHON:-python3}"
MD="${RUN_ALL_MD:-$HERE/RUN_ALL.md}"
TIMEOUT_S="${RUN_ALL_TIMEOUT:-7200}"
STAGES_RUN="${RUN_ALL_STAGES:-train val}"
TRAIN_ARGS="${RUN_ALL_TRAIN_ARGS:-}"
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
LOG_DIR="${RUN_ALL_LOG_DIR:-${TMPDIR:-/tmp}/lab2_run_all/$RUN_ID}"

utc() { date -u '+%Y-%m-%d %H:%M:%S'; }

is_hypothesis_module() {   # the stage CLI every hypothesis module shares (m1.py's conventions)
  grep -q '^STAGES = ' "$1" && grep -q '^def main(' "$1" && grep -q -- '"--stage"' "$1"
}

discover() {
  local f name
  for name in g1 m1 s1 d1; do
    f="$HERE/$name.py"
    [[ -f "$f" ]] && is_hypothesis_module "$f" && echo "$name"
  done
  for f in $(ls "$HERE"/x*.py "$HERE"/y*.py "$HERE"/z*.py 2>/dev/null | sort -V); do
    is_hypothesis_module "$f" && basename "$f" .py
  done
}

for st in $STAGES_RUN; do
  case "$st" in
    train|val) ;;
    *) echo "run_all.sh: stage '$st' is not allowed (train and val only; TEST / CONFIRM / FINAL are run by hand)" >&2
       exit 64 ;;
  esac
done

mapfile -t ALL < <(discover)
if [[ "${1:-}" == "--list" ]]; then
  printf '%s\n' "${ALL[@]}"
  exit 0
fi
if (($#)); then
  MODS=()
  for m in "$@"; do
    m="${m%.py}"
    if printf '%s\n' "${ALL[@]}" | grep -qx -- "$m"; then MODS+=("$m")
    else echo "run_all.sh: '$m' is not a discovered hypothesis module (see --list)" >&2; exit 64; fi
  done
else
  MODS=("${ALL[@]}")
fi
if ((${#MODS[@]} == 0)); then
  echo "run_all.sh: no hypothesis modules found in $HERE" >&2
  exit 66
fi

# one run_all at a time (the trials ledger has its own lock; this keeps RUN_ALL.md sections whole)
exec 9>"${TMPDIR:-/tmp}/lab2_run_all.lock"
if ! flock -n 9; then
  echo "run_all.sh: another run_all.sh is running" >&2
  exit 75
fi

mkdir -p "$LOG_DIR"
if [[ ! -s "$MD" ]]; then
  cat >"$MD" <<'EOF'
# lab2 run_all results

Appended by `research/lab2/run_all.sh`: TRAIN, then VAL, for every discovered hypothesis module (never TEST, CONFIRM
or FINAL). One section per invocation, one row per (module, stage). `exit` 0 = the stage ran and wrote its
`<ID>/<stage>.json` (or `_prelim` for a provisional TRAIN); 2 = refused by the module's own prerequisites; 124 =
timeout; anything else = an error (see the log). `result` is the written document's decision and overall status, or
the module's last message.
EOF
fi
{
  echo
  echo "## Run $RUN_ID ($(utc) UTC)"
  echo
  echo "- Modules (${#MODS[@]}, discovered by glob): ${MODS[*]}"
  echo "- Stages: $STAGES_RUN; TRAIN args: ${TRAIN_ARGS:-none}; timeout ${TIMEOUT_S} s per stage; logs: \`$LOG_DIR\`"
  echo
  echo "| UTC | module | stage | exit | seconds | result |"
  echo "|---|---|---|---:|---:|---|"
} >>"$MD"

summary() {   # $1 = module, $2 = stage, $3 = start epoch, $4 = log file
  "$PY" - "$HERE/${1^^}" "$2" "$3" "$4" <<'PY'
import json, os, sys
d, stage, t0, log = sys.argv[1], sys.argv[2], float(sys.argv[3]), sys.argv[4]
docs = [os.path.join(d, f"{n}.json") for n in (stage, stage + "_prelim")]
docs = [p for p in docs if os.path.exists(p) and os.path.getmtime(p) >= t0 - 1]
if docs:
    p = max(docs, key=os.path.getmtime)
    try:
        doc = json.load(open(p))
        dec = doc.get("decision") if isinstance(doc.get("decision"), dict) else {}
        ver = doc.get("verdict") if isinstance(doc.get("verdict"), dict) else {}
        v = dec.get("verdict") or ver.get("verdict") or doc.get("status")
        prov = " (PROVISIONAL)" if doc.get("provisional") or doc.get("preliminary") else ""
        print(f"{os.path.basename(p)}{prov}: decision {v}; overall {doc.get('overall')}")
        sys.exit(0)
    except (OSError, ValueError):
        pass
lines = [x.strip() for x in open(log, errors="replace") if x.strip()]
pick = [x for x in lines if "REFUSED" in x] or lines[-1:] or ["(no output)"]
print(pick[-1])
PY
}

for m in "${MODS[@]}"; do
  for st in $STAGES_RUN; do
    log="$LOG_DIR/${m}_${st}.log"
    args=(--stage "$st")
    [[ "$st" == "train" && -n "$TRAIN_ARGS" ]] && read -r -a extra <<<"$TRAIN_ARGS" && args+=("${extra[@]}")
    echo "$(utc) == $m ${args[*]}"
    t0=$(date +%s)
    (cd "$REPO" && env -u LAB2_ALLOW_TEST -u LAB2_ALLOW_CONFIRM -u LAB2_ALLOW_FINAL \
      timeout "$TIMEOUT_S" "$PY" "$HERE/$m.py" "${args[@]}") >"$log" 2>&1
    rc=$?
    secs=$(($(date +%s) - t0))
    res="$(summary "$m" "$st" "$t0" "$log" 2>/dev/null | tail -1)"
    res="${res//|/\\|}"
    res="${res:0:400}"
    echo "| $(utc) | $m | $st | $rc | $secs | $res |" >>"$MD"
    echo "$(utc)    exit $rc in ${secs}s: $res"
  done
done
echo "$(utc) done: rows appended to $MD"
