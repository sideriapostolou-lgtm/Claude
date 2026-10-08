"""Does the lab's 1-minute SOL/USD lookahead change any F4-#1 decision? Re-run the independent strategy using
only SOL minutes that have CLOSED by the decision time and compare signals and returns (auditor).

    OMP_NUM_THREADS=1 python research/lab/audit/sol_lag.py  -> LAB/audit/sol_lag_check.json
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import indep_f4 as I  # noqa: E402

out = {}
for split in ("test", "validation"):
    base = json.loads((I.OUT / f"indep_{split}_q98.json").read_text())["trades"]
    lag = I.run(split, 0.98, sol_shift_s=60)["trades"]
    a = [(t["mint"], t["decision_bar"], round(t.get("ret_pct", 0), 3)) for t in base]
    b = [(t["mint"], t["decision_bar"], round(t.get("ret_pct", 0), 3)) for t in lag]
    out[split] = {"same_signals": [x[:2] for x in a] == [x[:2] for x in b], "n_base": len(a), "n_lag": len(b),
                  "mean_ret_base": round(sum(x[2] for x in a) / len(a), 4),
                  "mean_ret_lag": round(sum(x[2] for x in b) / len(b), 4),
                  "max_abs_ret_diff": round(max(abs(x[2] - y[2]) for x, y in zip(a, b)), 4) if len(a) == len(b) else None}
    print(split, out[split], flush=True)
(I.OUT / "sol_lag_check.json").write_text(json.dumps(out, indent=1))
