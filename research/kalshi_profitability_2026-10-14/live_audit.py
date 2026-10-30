"""Summarize the fixed post-restart log capture; never submit orders or infer inverse fills."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent


def distribution(values: list[float]) -> dict[str, float | int | None]:
    """Linear sample quantiles, with the observation count alongside them."""
    values = sorted(values)

    def quantile(q: float) -> float | None:
        if not values:
            return None
        index = (len(values) - 1) * q
        lo = int(index)
        hi = min(lo + 1, len(values) - 1)
        return round(values[lo] + (values[hi] - values[lo]) * (index - lo), 3)

    return {"n": len(values), "p50_ms": quantile(0.5), "p95_ms": quantile(0.95),
            "max_ms": round(values[-1], 3) if values else None}


def summarize(events: list[dict[str, Any]]) -> dict[str, Any]:
    accepted = [row for row in events if row["event"] == "speeddesk_live_order"
                and row.get("state") == "accepted; waiting for real fills"]
    fills = [row for row in events if row["event"] == "speeddesk_live_fill"]
    settled = [row for row in events if row["event"] == "speeddesk_live_settlement"]
    cancels = [row for row in events if row["event"] == "speeddesk_live_cancel"]
    ack = [float(row["timing"]["value_ms"]) for row in accepted
           if (row.get("timing") or {}).get("value_ms") is not None]
    cancel = [float(row["timing"]["decision_to_ack_ms"]) for row in cancels
              if (row.get("timing") or {}).get("decision_to_ack_ms") is not None]
    windows: dict[str, dict[str, Any]] = {}
    for row in fills:
        value = windows.setdefault(row["window"], {"fills": 0, "up": 0.0, "down": 0.0,
                                                   "cost_usd": 0.0, "fees_usd": 0.0,
                                                   "settled_pnl_usd": None})
        value["fills"] += 1
        value[row["side"]] += row["size"]
        value["cost_usd"] += row["size"] * row["price"]
        value["fees_usd"] += row["fee_usd"]
    for row in settled:
        value = windows[row["window"]]
        assert abs(value["cost_usd"] - row["cost_usd"]) < 1e-8
        assert abs(value["fees_usd"] - row["fee_usd"]) < 1e-8
        assert abs(value["up"] - row["up_shares"]) < 1e-8
        assert abs(value["down"] - row["down_shares"]) < 1e-8
        value["settled_pnl_usd"] = row["pnl_usd"]
    return {
        "scope": "2026-10-14 14:05–14:25 UTC, deployment 02907385; no earlier cohorts pooled",
        "accepted_orders": len(accepted), "fill_receipts": len(fills),
        "cancel_receipts": len(cancels),
        "cancel_states": dict(Counter(str(row.get("state")) for row in cancels)),
        "order_decision_to_ack": distribution(ack), "cancel_decision_to_ack": distribution(cancel),
        "windows": windows,
        "settled_pnl_usd": sum(row["pnl_usd"] for row in settled),
        "settled_locked_usd": sum(row["locked_usd"] for row in settled),
        "settled_directional_usd": sum(row["direction_usd"] for row in settled),
        "inverse_pnl_usd": None,
        "limitations": [
            "A short observational sample, not an A/B test of the optional pull setting.",
            "Open-window costs are not realized losses; only settlement receipts contribute to P&L.",
            "Cancel latency includes reply processing; it does not prove when liquidity disappeared.",
            "Accepted orders, intents, fills and cancelled quantities are different measurements.",
            "Opposing executable books and queue evidence are absent; inverse profit is unmeasurable.",
        ],
    }


def main() -> None:
    capture = json.loads((ROOT / "live_events_1405_1425.json").read_text())
    result = summarize(capture["events"])
    output = ROOT / "live_summary_1405_1425.json"
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
