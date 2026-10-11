#!/usr/bin/env bash
# research/lab2/run_all.sh -- run every lab2 hypothesis module's TRAIN stage, then its VAL stage, and append the
# results to research/lab2/RUN_ALL.md as a table: hypothesis, stage, config, verdict, n trades, mean net, 95% CI,
# placebo mean, trials so far.
#
# Modules are DISCOVERED by glob, never listed by hand: g1 m1 s1 d1 first, then every other <letter><digit>*.py in
# research/lab2 in version order (q1 x1 ... x6 y1 ... z5, x2 before x10). A file counts as a hypothesis module only
# when it has the stage CLI (a module-level STAGES tuple, a main() and a --stage argument), so helpers such as
# common.py or b1_select.py are never run. A new designer's module is picked up without editing this script.
#
# It NEVER runs TEST, CONFIRM or FINAL: the only stages it passes are train and val, and it removes the judge's flags
# (LAB2_ALLOW_TEST, LAB2_ALLOW_CONFIRM, LAB2_ALLOW_FINAL) from every child's environment. Those looks are spent one
# hypothesis at a time, by hand, with the flag set.
#
# Each module enforces its own prerequisites: a stage that may not run exits 2 with "REFUSED ..." (TRAIN data still
# incomplete, S1 / D1 without B1, a stop-rule KILL, VAL without a shortlist or already run) and is logged as a REFUSED
# row; the run continues. Any other non-zero exit is logged as ERROR (exit code, last stderr line). VAL is attempted
# after every TRAIN (the module refuses it unless an official TRAIN wrote a shortlist), so a second invocation picks
# up modules whose TRAIN ran earlier.
#
# Rows: one per evaluated config (gated configs, hosts, G1's gated hosts) of a stage that ran, or one row with the
# verdict when nothing was evaluated (e.g. a pre-P&L stop rule) or the stage refused. "*" after the verdict marks the
# shortlisted / candidate config where the module's decision names it. 95% CI = the coin bootstrap; a module that
# reports only the 6-h block or a 90% CI gets that one, labelled. Placebo mean = the matched control's raw mean.
# Trials so far = the trials ledger total after the stage (the wave-1 baseline + every wave-2 config).
#
# Usage:
#   research/lab2/run_all.sh                    # every discovered module: --stage train, then --stage val
#   research/lab2/run_all.sh y1 x5              # only these modules (each must be a discovered module)
#   research/lab2/run_all.sh --list             # print the discovered modules and exit
#   research/lab2/run_all.sh --dry-run          # print the commands it would run; run and write nothing
#   research/lab2/run_all.sh --allow-partial    # provisional TRAIN on incomplete data (never unlocks VAL)
#   RUN_ALL_STAGES=train research/lab2/run_all.sh                  # TRAIN only (any subset of: train val)
#   RUN_ALL_TRAIN_ARGS=--allow-partial research/lab2/run_all.sh    # same as --allow-partial
#
# Env: PYTHON (default python3); RUN_ALL_TIMEOUT seconds per stage (default 7200); RUN_ALL_MD (default
# research/lab2/RUN_ALL.md); RUN_ALL_LOG_DIR (default ${TMPDIR:-/tmp}/lab2_run_all/<run id>: full output per stage);
# RUN_ALL_LAB_DIR (default: this script's directory; the tests point it at a fake lab).
# Exit: 0 = every stage ran or was refused by its module; 1 = some stage errored; 64 = bad arguments; 66 = no
# modules; 75 = another run_all.sh is running.
set -u

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LAB="${RUN_ALL_LAB_DIR:-$HERE}"
REPO="$(cd "$HERE/../.." && pwd)"
PY="${PYTHON:-python3}"
MD="${RUN_ALL_MD:-$LAB/RUN_ALL.md}"
TIMEOUT_S="${RUN_ALL_TIMEOUT:-7200}"
STAGES_RUN="${RUN_ALL_STAGES:-train val}"
TRAIN_ARGS="${RUN_ALL_TRAIN_ARGS:-}"
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
LOG_DIR="${RUN_ALL_LOG_DIR:-${TMPDIR:-/tmp}/lab2_run_all/$RUN_ID}"
CORE=(g1 m1 s1 d1)

utc() { date -u '+%Y-%m-%d %H:%M:%S'; }

is_hypothesis_module() {   # the stage CLI every hypothesis module shares (m1.py's conventions)
  grep -q '^STAGES = ' "$1" && grep -q '^def main(' "$1" && grep -q -- '"--stage"' "$1"
}

discover() {
  local f name
  for name in "${CORE[@]}"; do
    f="$LAB/$name.py"
    [[ -f "$f" ]] && is_hypothesis_module "$f" && echo "$name"
  done
  while IFS= read -r f; do
    name="$(basename "$f" .py)"
    [[ " ${CORE[*]} " == *" $name "* ]] && continue
    is_hypothesis_module "$f" && echo "$name"
  done < <(find "$LAB" -maxdepth 1 -name '[a-z][0-9]*.py' | sort -V)
}

LIST=0
DRY=0
ARGS_MODS=()
for a in "$@"; do
  case "$a" in
    --list) LIST=1 ;;
    --dry-run) DRY=1 ;;
    --allow-partial) [[ " $TRAIN_ARGS " == *" --allow-partial "* ]] || TRAIN_ARGS="${TRAIN_ARGS:+$TRAIN_ARGS }--allow-partial" ;;
    -h|--help) awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "${BASH_SOURCE[0]}"; exit 0 ;;
    -*) echo "run_all.sh: unknown option '$a' (see --help)" >&2; exit 64 ;;
    *) ARGS_MODS+=("${a%.py}") ;;
  esac
done

for st in $STAGES_RUN; do
  case "$st" in
    train|val) ;;
    *) echo "run_all.sh: stage '$st' is not allowed (train and val only; TEST / CONFIRM / FINAL are run by hand)" >&2
       exit 64 ;;
  esac
done
for x in $TRAIN_ARGS; do
  case "$x" in
    --stage*|test|confirm|final) echo "run_all.sh: RUN_ALL_TRAIN_ARGS may not name a stage ('$x')" >&2; exit 64 ;;
  esac
done

mapfile -t ALL < <(discover)
if ((LIST)); then
  printf '%s\n' "${ALL[@]}"
  exit 0
fi
if ((${#ARGS_MODS[@]})); then
  MODS=()
  for m in "${ARGS_MODS[@]}"; do
    if printf '%s\n' "${ALL[@]}" | grep -qx -- "$m"; then MODS+=("$m")
    else echo "run_all.sh: '$m' is not a discovered hypothesis module (see --list)" >&2; exit 64; fi
  done
else
  MODS=("${ALL[@]}")
fi
if ((${#MODS[@]} == 0)); then
  echo "run_all.sh: no hypothesis modules found in $LAB" >&2
  exit 66
fi

if ((DRY)); then
  for m in "${MODS[@]}"; do
    for st in $STAGES_RUN; do
      extra=""
      [[ "$st" == "train" && -n "$TRAIN_ARGS" ]] && extra=" $TRAIN_ARGS"
      echo "$PY $LAB/$m.py --stage $st$extra"
    done
  done
  exit 0
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
or FINAL). One section per invocation. A REFUSED row is a module enforcing its own pre-registered rules (data gates,
stop rules, one VAL look), not a failure of this script; ERROR rows are failures (see the per-stage log).

- **config**: one row per evaluated config of a stage that ran (gated configs, `host …` baselines, G1's gated hosts);
  `-` when the stage refused or evaluated nothing (e.g. a pre-P&L stop rule fired).
- **verdict**: the stage's decision; `*` marks the shortlisted / candidate config where the module's decision names
  it. PROVISIONAL / PRELIMINARY = `--allow-partial` on incomplete TRAIN: it writes no shortlist, so VAL refuses.
- **mean net / 95% CI**: per $20 trade after costs and worst fills; the CI is the coin bootstrap unless labelled
  (6-h block or 90%, where a module reports no coin 95% CI). `hidden` = the module hides returns on that split.
- **placebo mean**: the matched random control's raw mean (the signal's edge over it is in the module's report).
- **trials so far**: the trials ledger total after the stage (wave-1 baseline + every distinct wave-2 config).
- TRAIN rows are a search over each module's pre-registered grid: a positive TRAIN mean is not evidence of an edge.
EOF
fi
{
  echo
  echo "## Run $RUN_ID ($(utc) UTC)"
  echo
  echo "- Modules (${#MODS[@]}, discovered by glob): ${MODS[*]}"
  echo "- Stages: $STAGES_RUN; TRAIN args: ${TRAIN_ARGS:-none}; timeout ${TIMEOUT_S} s per stage; git" \
       "$(git -C "$REPO" rev-parse --short HEAD 2>/dev/null || echo n/a); logs: \`$LOG_DIR\`"
  echo
  echo "| hypothesis | stage | config | verdict | n trades | mean net | 95% CI | placebo mean | trials so far |"
  echo "|---|---|---|---|---:|---:|---|---:|---:|"
} >>"$MD"

rows() {   # $1 module, $2 stage, $3 exit code, $4 start epoch, $5 log: append the stage's rows; print a summary
  "$PY" - "$LAB" "$1" "$2" "$3" "$4" "$5" "$MD" "$HERE" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

lab, mod, stage, rc, t0, log, md, here = sys.argv[1:9]
rc, t0, ID = int(rc), float(t0), mod.upper()


def esc(x) -> str:
    s = " ".join(str(x).split())
    s = (s[:297] + "...") if len(s) > 300 else s
    return s.replace("|", "\\|")


def pct(x) -> str:
    return "n/a" if x is None else f"{100 * float(x):+.1f}%"


def ci_str(c, label: str = "") -> str:
    return "n/a" if not c else f"[{100 * float(c[0]):+.1f}%, {100 * float(c[1]):+.1f}%]{label}"


def phash(p) -> str:          # common.params_hash, replicated so that a broken common.py cannot break the log
    s = json.dumps(p or {}, sort_keys=True, default=repr, separators=(",", ":"))
    return hashlib.sha1(s.encode()).hexdigest()[:12]


def trials_now():
    try:
        sys.path.insert(0, here)
        import common
        return common.n_trials()
    except Exception:          # noqa: BLE001 -- the log must never fail on the ledger
        return "n/a"


def last_message() -> tuple[str, bool]:
    try:
        lines = [x.strip() for x in Path(log).read_text(errors="replace").splitlines() if x.strip()]
    except OSError:
        lines = []
    ref = [x for x in lines if "REFUSED" in x]
    s = (ref or lines or ["(no output)"])[-1]
    for pre in (f"REFUSED ({stage}): ", f"REFUSED: --stage {stage}: ", "REFUSED: "):
        if s.startswith(pre):
            s = s[len(pre):]
            break
    return s, bool(ref)


def row(config, verdict, n="", mean="", ci="", plm="", trials="") -> str:
    return f"| {ID} | {stage} | {esc(config)} | {esc(verdict)} | {n} | {mean} | {ci} | {plm} | {trials} |"


def verdict_of(doc: dict) -> str:
    dec = doc.get("decision") if isinstance(doc.get("decision"), dict) else {}
    ver = doc.get("verdict") if isinstance(doc.get("verdict"), dict) else {}
    v = dec.get("verdict") or dec.get("status") or ver.get("verdict") or doc.get("status")
    if not v and isinstance(dec.get("shortlist"), list):
        v = f"SHORTLIST of {len(dec['shortlist'])}"
    v = str(v or "done")
    if (doc.get("provisional") or doc.get("preliminary")) and not v.startswith(("PRELIMINARY", "PROVISIONAL")):
        v = f"PROVISIONAL {v}"
    return v


def selected(doc: dict) -> tuple[set, set]:
    dec = doc.get("decision") if isinstance(doc.get("decision"), dict) else {}
    keys = {str(x) for x in (dec.get("ranked") or []) if isinstance(x, str)}
    keys |= {dec[f] for f in ("candidate", "best", "candidate_config", "candidate_role") if isinstance(dec.get(f), str)}
    hashes = {h for h in (dec.get("shortlist_hashes") or []) if isinstance(h, str)}
    hashes |= {dec["candidate_hash"]} if isinstance(dec.get("candidate_hash"), str) else set()
    hashes |= {phash(p) for p in (dec.get("shortlist") or []) if isinstance(p, dict)}
    return keys, hashes


def evals_of(doc: dict) -> list:
    keys, hashes = selected(doc)
    has_n = lambda e: isinstance(e, dict) and ("n" in e or "n" in (e.get("summary") or {}))   # noqa: E731
    out = []
    conf = doc.get("configs")
    if isinstance(conf, dict):
        items = list(conf.items())
    elif isinstance(conf, list):
        items = [(str(e.get("label") or e.get("config") or i), e) for i, e in enumerate(conf) if isinstance(e, dict)]
    else:
        items = []
    for k, e in items:
        if has_n(e):
            c = e.get("config")
            name = k if c in (None, k) else f"{k}: {c}"
            sel = (k in keys or c in keys or e.get("params_hash") in hashes
                   or (isinstance(e.get("params"), dict) and phash(e["params"]) in hashes))
            out.append((name, e, sel))
    hosts = doc.get("hosts")
    for k, e in (hosts.items() if isinstance(hosts, dict) else []):
        if has_n(e):
            out.append((f"host {k}", e, False))
    ve = doc.get("variants_eval")
    for vname, v in (ve.items() if isinstance(ve, dict) else []):
        hs = v.get("hosts") if isinstance(v, dict) else None
        for h, cell in (hs.items() if isinstance(hs, dict) else []):
            g = cell.get("gated") if isinstance(cell, dict) else None
            if has_n(g):
                out.append((f"{vname} gated {h}", g, False))
    return out


out_rows, summary = [], ""
msg, refused = last_message()
if rc != 0:
    refused = refused and rc == 2
    out_rows.append(row("-", ("REFUSED: " if refused else f"ERROR (exit {rc}{', timeout' if rc == 124 else ''}): ")
                        + msg, trials=trials_now()))
    summary = "REFUSED" if refused else "ERROR"
else:
    cands = [Path(lab) / ID / f"{stage}{suf}.json" for suf in ("", "_prelim")]
    fresh = [p for p in cands if p.exists() and p.stat().st_mtime >= t0 - 1]
    doc = None
    if fresh:
        try:
            doc = json.loads(max(fresh, key=lambda p: p.stat().st_mtime).read_text())
        except (OSError, ValueError):
            doc = None
    if not isinstance(doc, dict):
        out_rows.append(row("-", f"ERROR: exit 0 but no readable {ID}/{stage}.json was written ({msg})",
                            trials=trials_now()))
        summary = "ERROR"
    else:
        v = verdict_of(doc)
        trials = doc.get("n_trials_total") or trials_now()
        ev = evals_of(doc)
        for name, e, sel in ev:
            s = e if ("mean" in e or not isinstance(e.get("summary"), dict)) else e["summary"]
            n = e.get("n", s.get("n"))
            c, label = s.get("ci95"), ""
            if not c and s.get("ci95_block"):
                c, label = s["ci95_block"], " (6-h block)"
            if not c and s.get("ci90"):
                c, label = s["ci90"], " (90%)"
            pl = e.get("placebo") if isinstance(e.get("placebo"), dict) else {}
            mean = pct(s.get("mean")) if "mean" in s else ("hidden" if "returns" in e else "n/a")
            out_rows.append(row(name, v + (" *" if sel else ""), "" if n is None else n, mean, ci_str(c, label),
                                pct(pl.get("placebo_mean")) if pl.get("placebo_mean") is not None else "n/a", trials))
        if not ev:
            out_rows.append(row("-", v, trials=trials))
        summary = f"{v} ({len(ev)} configs)"
with open(md, "a") as f:
    f.write("\n".join(out_rows) + "\n")
print(summary)
PY
}

n_ok=0; n_ref=0; n_err=0
for m in "${MODS[@]}"; do
  for st in $STAGES_RUN; do
    log="$LOG_DIR/${m}_${st}.log"
    args=(--stage "$st")
    if [[ "$st" == "train" && -n "$TRAIN_ARGS" ]]; then read -r -a extra <<<"$TRAIN_ARGS"; args+=("${extra[@]}"); fi
    echo "$(utc) == $m ${args[*]}"
    t0=$(date +%s)
    (cd "$REPO" && env -u LAB2_ALLOW_TEST -u LAB2_ALLOW_CONFIRM -u LAB2_ALLOW_FINAL \
      timeout "$TIMEOUT_S" "$PY" "$LAB/$m.py" "${args[@]}") >"$log" 2>&1
    rc=$?
    secs=$(($(date +%s) - t0))
    res="$(rows "$m" "$st" "$rc" "$t0" "$log" 2>>"$log" | tail -1)"
    case "$res" in
      REFUSED*) n_ref=$((n_ref + 1)) ;;
      ERROR*|"")
        n_err=$((n_err + 1))
        if [[ -z "$res" ]]; then
          res="ERROR: the result logger failed (see $log)"
          echo "| ${m^^} | $st | - | ${res//|/\\|} |  |  |  |  |  |" >>"$MD"
        fi ;;
      *) n_ok=$((n_ok + 1)) ;;
    esac
    echo "$(utc)    exit $rc in ${secs}s: $res"
  done
done
{
  echo
  echo "Stages that ran: $n_ok; refused by their module: $n_ref; errors: $n_err."
} >>"$MD"
echo "$(utc) done: $n_ok ran, $n_ref refused, $n_err errors; table in $MD; logs in $LOG_DIR"
((n_err == 0))
