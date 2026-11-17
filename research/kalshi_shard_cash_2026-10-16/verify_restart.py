"""Compare selected native status evidence; no account access or financial actions."""

from __future__ import annotations

import json
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parent
    before = json.loads((root / "BEFORE.json").read_text())["rows"][-1]
    after = json.loads((root / "AFTER.json").read_text())["rows"][-1]
    fields = ("configured_mode", "mode", "caps", "day_stop_latched", "total_halted",
              "integrity_error", "open_risk_usd", "open_cost_usd", "reserved_usd",
              "at_risk_usd", "open_orders", "positions")
    checks = {name: before[name] == after[name] for name in fields}
    for scope in ("today", "total"):
        for name in ("windows", "fills", "fees_usd", "locked_usd", "directional_usd", "pnl_usd", "worst_usd"):
            checks[f"{scope}.{name}"] = before[scope][name] == after[scope][name]
    checks["paper_preserved"] = after["configured_mode"] == after["mode"] == "paper"
    checks["no_authenticated_account_read"] = after["authenticated"] is False
    result = {"before": before["timestamp"], "after": after["timestamp"],
              "checks": checks, "passed": all(checks.values()),
              "limitation": "Selected logged snapshots only; not raw ledger, budget-anchor, "
                            "credential, volume or continuous-coverage verification."}
    print(json.dumps(result, indent=2, sort_keys=True))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
