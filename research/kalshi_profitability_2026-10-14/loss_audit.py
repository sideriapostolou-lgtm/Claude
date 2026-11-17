"""Reconcile already-published real fills; never replay an alternative strategy.

Only the two named historical CSVs are read. No network, credentials, account
state, model fitting, or held-out TEST access. Run from any directory.
"""

from __future__ import annotations

import csv
import hashlib
import json
from collections import defaultdict
from decimal import Decimal as D
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
INPUT = HERE.parent / "handoff_2026-10-14"
ZERO = D(0)


def read_csv(name: str) -> list[dict[str, str]]:
    with (INPUT / name).open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def amount(value: D) -> str:
    return str(value.quantize(D(".0001")))


def audit() -> dict[str, Any]:
    windows = read_csv("windows.csv")
    orders = read_csv("orders.csv")
    fills_by_window: dict[str, list[dict[str, str]]] = defaultdict(list)
    for order in orders:
        if D(order["filled"]) > 0:
            fills_by_window[order["window"]].append(order)

    totals: dict[str, D] = defaultdict(lambda: ZERO)
    counts: dict[str, int] = defaultdict(int)
    max_cost_error = ZERO
    max_fee_error = ZERO
    max_quantity_error = ZERO
    worst = ZERO
    for window in windows:
        fills = fills_by_window[window["window"]]
        qty = {side: ZERO for side in ("up", "down")}
        cost = qty.copy()
        rest_qty = qty.copy()
        rest_cost = qty.copy()
        lock_qty = qty.copy()
        lock_cost = qty.copy()
        fees = ZERO
        for fill in fills:
            side = fill["side"]
            size = D(fill["filled"])
            paid = size * D(fill["avg_fill_price"])
            qty[side] += size
            cost[side] += paid
            fees += D(fill["fill_fee_usd"])
            counts[f"{fill['kind']}_orders_with_fills"] += 1
            totals[f"{fill['kind']}_filled_contracts"] += size
            totals[f"{fill['kind']}_fees"] += D(fill["fill_fee_usd"])
            if fill["kind"] == "rest":
                rest_qty[side] += size
                rest_cost[side] += paid
            elif fill["kind"] == "lock":
                lock_qty[side] += size
                lock_cost[side] += paid
            else:
                raise ValueError("This accounting expects the published maker/lock-only sample")

        paid = sum(cost.values(), ZERO)
        winner = window["outcome"].lower()
        pnl = qty[winner] - paid - fees
        settled_cost = D(window["sett_cost"])
        settled_fee = D(window["sett_fee"])
        max_cost_error = max(max_cost_error, abs(paid - settled_cost))
        max_fee_error = max(max_fee_error, abs(fees - settled_fee))
        max_quantity_error = max(max_quantity_error, *(abs(qty[s] - D(window[f"sett_{s}"]))
                                                      for s in qty))
        # Fill prices and settlement amounts are published to four decimal places.
        assert abs(pnl - D(window["pnl_usd"])) <= D(".001")
        assert abs(paid - settled_cost) <= D(".001")
        assert abs(fees - settled_fee) < D("1e-12")
        assert abs(qty[winner] - D(window["payout_usd"])) < D("1e-12")
        assert all(abs(qty[s] - D(window[f"sett_{s}"])) < D("1e-12") for s in qty)

        # Average-cost attribution, not an executable ordering or alternative policy.
        rest_avg = {s: rest_cost[s] / rest_qty[s] if rest_qty[s] else ZERO for s in qty}
        rest_pairs = min(rest_qty.values())
        maker_pair_gross = rest_pairs * (1 - sum(rest_avg.values()))
        remaining = {s: rest_qty[s] - rest_pairs for s in qty}
        lock_pair_gross = ZERO
        for side in qty:
            other = "down" if side == "up" else "up"
            assert lock_qty[side] <= remaining[other]
            lock_pair_gross += lock_qty[side] * (1 - rest_avg[other]) - lock_cost[side]
            remaining[other] -= lock_qty[side]
        leftover_gross = sum(remaining[s] * (int(s == winner) - rest_avg[s]) for s in qty)
        assert abs(maker_pair_gross + lock_pair_gross + leftover_gross - fees - pnl) < D("1e-20")

        prelock_difference = rest_qty["up"] - rest_qty["down"]
        if prelock_difference:
            counts["prelock_unbalanced_windows"] += 1
            heavy = "up" if prelock_difference > 0 else "down"
            counts["prelock_heavy_side_lost"] += int(heavy != winner)
        counts["wins"] += int(pnl > D(".00001"))
        counts["losses"] += int(pnl < -D(".00001"))
        counts["flat"] += int(abs(pnl) <= D(".00001"))
        counts["both_sides_filled_windows"] += int(min(qty.values()) > 0)
        counts["final_unbalanced_windows"] += int(qty["up"] != qty["down"])
        counts["fee_changed_win_to_loss"] += int(pnl < 0 <= pnl + fees)
        totals["maker_pair_gross"] += maker_pair_gross
        totals["lock_pair_gross"] += lock_pair_gross
        totals["unmatched_gross"] += leftover_gross
        totals["fees"] += fees
        totals["fill_cost"] += paid
        totals["settlement_cost"] += settled_cost
        totals["payout"] += qty[winner]
        totals["fill_reconstructed_net"] += pnl
        totals["published_settlement_net"] += D(window["pnl_usd"])
        totals["published_locked_net"] += D(window["locked_usd"])
        totals["published_direction_net"] += D(window["direction_usd"])
        # Accounting removal only: not a counterfactual execution replay.
        lock_net = lock_qty[winner] - sum(lock_cost.values()) - sum(
            D(f["fill_fee_usd"]) for f in fills if f["kind"] == "lock"
        )
        totals["actual_lock_leg_net"] += lock_net
        totals["actual_maker_legs_without_locks_net"] += pnl - lock_net
        worst = min(worst, pnl)

    return {
        "scope": "Accounting of published Oct 13 real fills, 16:00-23:15 UTC; not a policy backtest",
        "sources": {name: hashlib.sha256((INPUT / name).read_bytes()).hexdigest()
                    for name in ("windows.csv", "orders.csv")},
        "window_rows": len(windows),
        "order_intent_rows": len(orders),
        "order_intents_by_kind": {kind: sum(row["kind"] == kind for row in orders)
                                  for kind in sorted({row["kind"] for row in orders})},
        "counts": dict(counts),
        "contracts": {key: amount(value) for key, value in totals.items()
                      if key.endswith("filled_contracts")},
        "usd": {key: amount(value) for key, value in totals.items()
                if not key.endswith("filled_contracts")},
        "worst_window_net_usd": amount(worst),
        "mean_window_net_usd": amount(totals["published_settlement_net"] / len(windows)),
        "reconciliation": {
            "max_window_cost_rounding_difference_usd": amount(max_cost_error),
            "max_window_fee_difference_usd": amount(max_fee_error),
            "max_window_quantity_difference": str(max_quantity_error),
            "aggregate_cost_rounding_difference_usd": amount(
                totals["fill_cost"] - totals["settlement_cost"]),
        },
        "inversion": {
            "executable_inverse_pnl": None,
            "reason": "Missing contemporaneous opposing executable books, timing, queue, and independent policy state",
            "signal_significance": None,
            "reason_no_significance": "Selected losing interval, dependent windows, no pre-registered independent confirmation",
        },
        "heldout_test_accessed": False,
    }


if __name__ == "__main__":
    result = audit()
    rendered = json.dumps(result, indent=2) + "\n"
    (HERE / "loss_audit_summary.json").write_text(rendered, encoding="utf-8")
    print(rendered, end="")
