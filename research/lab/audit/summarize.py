"""Swap-level replay summary for F4-#1 on VALIDATION, TEST and pooled, at 1 / 2 / 5 s latency (auditor).

    python research/lab/audit/summarize.py  -> LAB/audit/replay_summary.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fragility as FR  # noqa: E402
import indep_f4 as I  # noqa: E402
import trade_replay as TR  # noqa: E402


def main() -> dict:
    out: dict = {}
    for lat in (1.0, 2.0, 5.0):
        per = {}
        for split in ("validation", "test"):
            res = TR.replay(str(I.OUT / f"indep_{split}_q98.json"), lat)
            (I.OUT / f"replay_{split}_lat{lat:g}.json").write_text(json.dumps(res, indent=1))
            per[split] = res["rows"]
        per["pooled"] = per["validation"] + per["test"]
        out[f"lat_{lat:g}s"] = {k: {**FR.stats(v),
                                    "undetermined": sum(r["trade_exit"] == "undetermined_window" for r in v),
                                    "incomplete_windows": sum(not r["complete"] for r in v)}
                                for k, v in per.items()}
    (I.OUT / "replay_summary.json").write_text(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    for lat, d in main().items():
        print(lat)
        for k, v in d.items():
            print(f"  {k}: {json.dumps(v)}")
