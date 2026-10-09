"""Tests for research/lab2/run_all.sh on a fake lab: discovery (version order, helpers skipped), TRAIN then VAL only
(never TEST / CONFIRM / FINAL, the judge's flags stripped from every child), refused vs errored stages, and the
RUN_ALL.md table (hypothesis, stage, config, verdict, n trades, mean net, 95% CI, placebo mean, trials so far)."""

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "run_all.sh"

MODULE = textwrap.dedent('''\
    """fake hypothesis module: behaviour per stage from BEHAVIOUR."""
    import json, os, sys, time
    from pathlib import Path
    HERE = Path(__file__).resolve().parent
    STAGES = ("train", "val", "test", "confirm", "final")
    BEHAVIOUR = {behaviour!r}


    def main():
        import argparse
        ap = argparse.ArgumentParser()
        ap.add_argument("--stage", choices=STAGES)
        ap.add_argument("--allow-partial", action="store_true")
        a = ap.parse_args()
        with open(HERE / "calls.jsonl", "a") as f:
            f.write(json.dumps({{"mod": Path(__file__).stem, "argv": sys.argv[1:],
                                "flags": sorted(k for k in os.environ if k.startswith("LAB2_ALLOW_"))}}) + "\\n")
        b = BEHAVIOUR.get(a.stage, "refuse")
        if b == "refuse":
            print(f"REFUSED ({{a.stage}}): no shortlist | nothing to do", file=sys.stderr)
            return 2
        if b == "crash":
            raise RuntimeError("boom")
        if b == "silent":
            return 0
        out = HERE / Path(__file__).stem.upper()
        out.mkdir(exist_ok=True)
        doc = dict(b)
        name = a.stage + ("_prelim" if a.allow_partial else "")
        if a.allow_partial:
            doc["provisional"] = True
        (out / f"{{name}}.json").write_text(json.dumps(doc))
        print("wrote", name)
        return 0


    if __name__ == "__main__":
        sys.exit(main())
''')

TRAIN_DOC = {"stage": "train", "n_trials_total": 2600,
             "decision": {"verdict": "SHORTLISTED", "shortlist_hashes": ["h1"]},
             "configs": {"a|1": {"config": "a|1", "params_hash": "h1", "n": 70, "mean": 0.05, "ci95": [0.01, 0.09],
                                 "placebo": {"placebo_mean": -0.02, "mean_diff": 0.07}},
                         "b|2": {"config": "b|2", "params_hash": "h2", "n": 12, "mean": -0.1, "ci90": [-0.2, 0.0],
                                 "placebo": None}},
             "hosts": {"R0": {"n": 300, "mean": -0.08, "ci95_block": [-0.12, -0.04]}}}
KILL_DOC = {"stage": "train", "n_trials_total": 2601,
            "decision": {"verdict": "KILLED_MODEL_CHECK", "note": "no P&L"}}


def fake_lab(root: Path) -> Path:
    lab = root / "lab"
    lab.mkdir()
    mods = {"g1": {"train": TRAIN_DOC, "val": "refuse"},
            "x1": {"train": "refuse", "val": "refuse"},
            "x2": {"train": "crash", "val": "refuse"},
            "x10": {"train": KILL_DOC, "val": "refuse"},
            "y1": {"train": "silent", "val": "refuse"}}
    for m, b in mods.items():
        (lab / f"{m}.py").write_text(MODULE.format(behaviour=b))
    (lab / "b1_select.py").write_text("def main():\n    raise SystemExit('a helper, never run')\n")
    (lab / "common.py").write_text("STAGES = ()\n")
    return lab


def run(lab: Path, root: Path, *args, **env_extra) -> subprocess.CompletedProcess:
    env = dict(os.environ, RUN_ALL_LAB_DIR=str(lab), RUN_ALL_MD=str(root / "RUN_ALL.md"),
               RUN_ALL_LOG_DIR=str(root / "logs"), TMPDIR=str(root), PYTHON=sys.executable,
               LAB2_ALLOW_TEST="1", LAB2_ALLOW_CONFIRM="1", LAB2_ALLOW_FINAL="1", **env_extra)
    return subprocess.run(["bash", str(SCRIPT), *args], env=env, capture_output=True, text=True, timeout=300)


def calls(lab: Path) -> list[dict]:
    p = lab / "calls.jsonl"
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


def table(md: Path) -> list[list[str]]:
    out = []
    for line in md.read_text().splitlines():
        if line.startswith("| ") and not line.startswith(("| hypothesis", "|---")):
            cells = [c.strip().replace("\\|", "|") for c in line.strip("|").split(" | ")]
            out.append(cells)
    return out


def test_discovery_order_and_helpers_skipped(tmp_path):
    lab = fake_lab(tmp_path)
    r = run(lab, tmp_path, "--list")
    assert r.returncode == 0 and r.stdout.split() == ["g1", "x1", "x2", "x10", "y1"]   # version order, no helpers
    assert run(lab, tmp_path, "b1_select").returncode == 64


def test_train_then_val_only_and_the_table(tmp_path):
    lab = fake_lab(tmp_path)
    r = run(lab, tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr                       # x2 crashed (an ERROR row), the rest logged
    cs = calls(lab)
    assert [(c["mod"], c["argv"]) for c in cs] == [(m, ["--stage", s]) for m in ("g1", "x1", "x2", "x10", "y1")
                                                  for s in ("train", "val")]
    assert all(c["flags"] == [] for c in cs)                            # the judge's flags never reach a module
    rows = table(tmp_path / "RUN_ALL.md")
    by = {(r_[0], r_[1], r_[2]): r_ for r_ in rows}
    assert by[("G1", "train", "a|1")] == ["G1", "train", "a|1", "SHORTLISTED *", "70", "+5.0%", "[+1.0%, +9.0%]",
                                          "-2.0%", "2600"]
    assert by[("G1", "train", "b|2")][3:8] == ["SHORTLISTED", "12", "-10.0%", "[-20.0%, +0.0%] (90%)", "n/a"]
    assert by[("G1", "train", "host R0")][3:7] == ["SHORTLISTED", "300", "-8.0%", "[-12.0%, -4.0%] (6-h block)"]
    assert by[("G1", "val", "-")][3] == "REFUSED: no shortlist | nothing to do"
    assert by[("X1", "train", "-")][3].startswith("REFUSED") and by[("X1", "val", "-")][3].startswith("REFUSED")
    assert by[("X2", "train", "-")][3].startswith("ERROR (exit 1)") and "boom" in by[("X2", "train", "-")][3]
    assert by[("X10", "train", "-")][3] == "KILLED_MODEL_CHECK" and by[("X10", "train", "-")][8] == "2601"
    assert by[("Y1", "train", "-")][3].startswith("ERROR: exit 0 but no readable Y1/train.json")
    assert all(r_[8] for r_ in rows)                                    # trials so far on every row
    md = (tmp_path / "RUN_ALL.md").read_text()
    assert md.startswith("# lab2 run_all results") and "Stages that ran: 2; refused by their module: 6; errors: 2" in md
    assert (tmp_path / "logs" / "x2_train.log").exists()
    # a second invocation appends a new section, never rewrites the first
    run(lab, tmp_path, "g1")
    md2 = (tmp_path / "RUN_ALL.md").read_text()
    assert md2.startswith(md) and md2.count("## Run ") == 2


def test_allow_partial_reaches_train_only_and_is_marked(tmp_path):
    lab = fake_lab(tmp_path)
    r = run(lab, tmp_path, "--allow-partial", "g1")
    assert r.returncode == 0, r.stdout + r.stderr
    assert [c["argv"] for c in calls(lab)] == [["--stage", "train", "--allow-partial"], ["--stage", "val"]]
    rows = table(tmp_path / "RUN_ALL.md")
    assert {r_[3] for r_ in rows if r_[1] == "train"} == {"PROVISIONAL SHORTLISTED *", "PROVISIONAL SHORTLISTED"}


@pytest.mark.parametrize("args,env", [((), {"RUN_ALL_STAGES": "train test"}), (("test",), {}), (("confirm",), {}),
                                      ((), {"RUN_ALL_TRAIN_ARGS": "--stage final"}), (("--stage",), {})])
def test_never_a_sealed_stage(tmp_path, args, env):
    lab = fake_lab(tmp_path)
    r = run(lab, tmp_path, *args, **env)
    assert r.returncode == 64 and calls(lab) == [] and not (tmp_path / "RUN_ALL.md").exists()


def test_dry_run_runs_and_writes_nothing(tmp_path):
    lab = fake_lab(tmp_path)
    r = run(lab, tmp_path, "--dry-run", "--allow-partial")
    assert r.returncode == 0 and calls(lab) == [] and not (tmp_path / "RUN_ALL.md").exists()
    lines = r.stdout.splitlines()
    assert len(lines) == 10 and all(x.split()[-2:] in (["train", "--allow-partial"], ["--stage", "val"]) for x in lines)


def test_real_lab_discovers_every_hypothesis_module():
    r = subprocess.run(["bash", str(SCRIPT), "--list"], capture_output=True, text=True, timeout=60,
                       env={k: v for k, v in os.environ.items() if k != "RUN_ALL_LAB_DIR"})
    mods = r.stdout.split()
    assert r.returncode == 0 and mods[:4] == ["g1", "m1", "s1", "d1"]
    assert {f"x{i}" for i in range(1, 7)} <= set(mods) and not {"common", "b1_select"} & set(mods)
    d = subprocess.run(["bash", str(SCRIPT), "--dry-run"], capture_output=True, text=True, timeout=60)
    assert d.returncode == 0 and {x.split()[-1] for x in d.stdout.splitlines()} == {"train", "val"}
