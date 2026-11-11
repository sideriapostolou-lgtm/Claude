"""Audit inherited replay arithmetic only; this is not an executable policy replay.
Public research CSVs only. No network, production state, account credentials or TEST data.
The original simulator and parsed fill chronology were not included in the handoff.
"""

import csv
import json
from decimal import ROUND_FLOOR
from decimal import Decimal as D
from pathlib import Path

BASE = Path(__file__).resolve().parents[1] / "handoff_2026-10-14"
windows = list(csv.DictReader((BASE / "windows.csv").open()))
orders = list(csv.DictReader((BASE / "orders.csv").open()))


# Exact conservative per-.01-fill reserve used by the inherited live risk model.
def unit(price, coefficient):
    from decimal import ROUND_CEILING

    return ((price + coefficient * price * (1 - price)) / D(".01")).to_integral_value(
        rounding=ROUND_CEILING
    ) * D(".01")


def replay(anchor_mode, extra_hedge_fills=False):
    actual = D("1.9733")
    simulated = actual
    changes = []
    for window in windows:
        fills = sorted(
            (
                r
                for r in orders
                if r["window"] == window["window"] and D(r["filled"]) > 0
            ),
            key=lambda r: -D(r["first_fill_secs_before_close"]),
        )
        first = fills[0]
        prior = actual if anchor_mode == "actual" else simulated
        day_loss = max(D(0), D("-5.9928") - (prior - D("1.0653")))
        room = min(D(6) - day_loss, D(10) - max(D(0), -prior))
        price = D(first["price"])
        hedge = ((D(".99") - price) * 100).to_integral_value(rounding=ROUND_FLOOR) / 100
        pair = unit(price, D(0)) + unit(hedge, D(".07"))
        size = min(
            D(first["filled"]),
            max(
                D(0),
                ((room - D(".000000001")) / pair).to_integral_value(
                    rounding=ROUND_FLOOR
                ),
            ),
        )
        actual_pnl = D(window["pnl_usd"])
        if size == D(first["filled"]):
            pnl = actual_pnl
        else:
            qty = {"up": D(0), "down": D(0)}
            paid = D(0)
            for index, fill in enumerate(fills):
                side = fill["side"]
                other = "up" if side == "down" else "down"
                if index == 0:
                    count = size
                else:
                    available = max(D(0), qty[other] - qty[side])
                    count = min(D(fill["filled"]), available)
                    if extra_hedge_fills and fill["kind"] == "rest":
                        count = available
                qty[side] += count
                paid += count * D(fill["avg_fill_price"]) + D(
                    fill["fill_fee_usd"]
                ) * count / D(fill["filled"])
            pnl = qty[window["outcome"].lower()] - paid
        changes.append(
            {
                "time_pt": window["start_pt"],
                "actual_pnl": str(actual_pnl),
                "pnl": str(pnl),
                "first_actual_size": str(first["filled"]),
                "first_new_size": str(size),
                "starting_reference_pnl": str(prior),
                "hedged_pair_reserve": str(pair),
            }
        )
        actual += actual_pnl
        simulated += pnl
    return {
        "mode": anchor_mode,
        "extra_hedge_fills": extra_hedge_fills,
        "pnl": str(simulated - D("1.9733")),
        "windows": changes,
    }


actual_cost = sum(
    D(r["filled"]) * D(r["avg_fill_price"]) for r in orders if D(r["filled"]) > 0
)
actual_fees = sum(D(r["fill_fee_usd"]) for r in orders)
actual_payout = sum(D(r["payout_usd"]) for r in windows)
result = {
    "actual": {
        "windows": len(windows),
        "order_rows": len(orders),
        "filled_orders": sum(D(r["filled"]) > 0 for r in orders),
        "cost": str(actual_cost),
        "fees": str(actual_fees),
        "payout": str(actual_payout),
        "pnl": str(actual_payout - actual_cost - actual_fees),
    },
    "reconstructions": [replay("actual"), replay("simulated"), replay("actual", True)],
    "warning": "Arithmetic sensitivity illustration only: historical fill selection, no queue or timing replay, actual anchors condition later risk on losses our modified trades did not incur, fees scaled from actual fills, no counterfactual additional decisions or explicit latch/pull/cancel/reconcile state machine.",
}
Path(__file__).with_suffix(".json").write_text(json.dumps(result, indent=2) + "\n")
print(
    json.dumps(
        {
            "actual": result["actual"],
            "totals": [
                {
                    "mode": x["mode"],
                    "extra_hedge_fills": x["extra_hedge_fills"],
                    "pnl": x["pnl"],
                }
                for x in result["reconstructions"]
            ],
        },
        indent=2,
    )
)
for x in result["reconstructions"][0]["windows"]:
    if x["pnl"] != x["actual_pnl"]:
        print(
            x["time_pt"],
            x["actual_pnl"],
            "->",
            x["pnl"],
            "starter",
            x["first_actual_size"],
            "->",
            x["first_new_size"],
        )
