"""Reconcile a bounded post-PR75 log cohort; no network, strategy fitting or simulated fills."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent
INHERITED = "KXBTC15M-26OCT161645-45"
TARGET = "KXBTC15M-26OCT161815-15"
TOLERANCE = Decimal("0.00000001")


def read(name):
    return json.loads((ROOT / name).read_text())


def events(rows):
    for row in rows:
        match = re.search(r"nightcrawler\.speeddesk: (\w+) (\{.*\})$", row["message"])
        if match:
            yield {"log_at": row["timestamp"], "event": match[1], **json.loads(match[2])}


def dec(value):
    return Decimal(str(value))


def amount(value):
    return str(value.quantize(Decimal("0.0001")))


def main():
    checks = 0

    def check(condition):
        nonlocal checks
        assert condition
        checks += 1

    raw = read("MONEY_LOGS.json")
    check(len(raw["rows"]) < raw["scope"]["limit"])
    rows = list(events(raw["rows"]))
    fills = [row for row in rows if row["event"] == "speeddesk_live_fill"]
    settled = [row for row in rows if row["event"] == "speeddesk_live_settlement"]
    check(len({row["fill_id"] for row in fills}) == len(fills))
    check(len({row["settlement_id"] for row in settled}) == len(settled))
    by_window = defaultdict(list)
    for row in fills:
        by_window[row["window"]].append(row)
    new = []
    for row in settled:
        net = dec(row["payout_usd"]) - dec(row["cost_usd"]) - dec(row["fee_usd"])
        check(abs(net - dec(row["pnl_usd"])) < TOLERANCE)
        if row["window"] == INHERITED:
            continue
        actual = by_window[row["window"]]
        for side in ("up", "down"):
            shares = sum((dec(fill["size"]) for fill in actual if fill["side"] == side), Decimal(0))
            check(abs(shares - dec(row[side + "_shares"])) < TOLERANCE)
        cost = sum((dec(fill["size"]) * dec(fill["price"]) for fill in actual), Decimal(0))
        fees = sum((dec(fill["fee_usd"]) for fill in actual), Decimal(0))
        check(abs(cost - dec(row["cost_usd"])) < TOLERANCE)
        check(abs(fees - dec(row["fee_usd"])) < TOLERANCE)
        check(abs(dec(row["locked_usd"]) + dec(row["direction_usd"]) - net) < TOLERANCE)
        new.append({"window": row["window"], "settled_event_at": row["at"], "log_at": row["log_at"],
                    "fills": len(actual), "up_wins": row["up_wins"], "cost_usd": amount(cost),
                    "fee_usd": amount(fees), "payout_usd": amount(dec(row["payout_usd"])),
                    "pnl_usd": amount(net)})
    new_net = sum((dec(row["pnl_usd"]) for row in new), Decimal(0))
    inherited = sum((dec(row["pnl_usd"]) for row in settled if row["window"] == INHERITED), Decimal(0))
    total = new_net + inherited
    after = read("STATUS.json")[-1]["data"]
    before = json.loads((ROOT.parent / "kalshi_hedge_completion_2026-10-16/RUNTIME.json").read_text())
    baseline = {key: dec(value) for key, value in before["fresh_observation"]["data"]["total"].items()
                if isinstance(value, (int, float))}
    current = after["total"]
    check(abs(dec(current["pnl_usd"]) - baseline["pnl_usd"] - total) < TOLERANCE)
    check(current["fills"] - baseline["fills"] == len(fills))
    check(current["settled_windows"] - baseline["settled_windows"] == len(settled))
    all_fees = sum((dec(row["fee_usd"]) for row in fills), Decimal(0))
    check(abs(dec(current["fees_usd"]) - baseline["fees_usd"] - all_fees) < TOLERANCE)
    check(abs(dec(current["directional_usd"]) - baseline["directional_usd"]) < TOLERANCE)
    check(abs(dec(current["locked_usd"]) - baseline["locked_usd"] - total) < TOLERANCE)
    old_status = before["fresh_observation"]["data"]
    cash_change = dec(after["cash_usd"]) - dec(old_status["cash_usd"])
    inventory_adjusted_change = total + dec(old_status["open_cost_usd"]) - dec(after["open_cost_usd"])
    check(abs(cash_change - inventory_adjusted_change) < TOLERANCE)
    target = [row for row in events(read("TARGET_ORDERS.json")["deploy"]) if row.get("window") == TARGET]
    intents = [row for row in target if row.get("state", "").startswith("durable intent")]
    target_fills = by_window[TARGET]
    first = next(row for row in target_fills if row["side"] == "down")
    hedge = next(row for row in target_fills if row["side"] == "up")
    lock = next(row for row in intents if row["client_order_id"] == hedge["client_order_id"])
    check(lock["kind"] == "lock")
    check(hedge["price"] <= lock["price"])
    no_hedge_actual_outcome = -dec(first["price"]) * dec(first["size"]) - dec(first["fee_usd"])
    losing = next(row for row in new if row["window"] == TARGET)
    check(dec(losing["pnl_usd"]) > no_hedge_actual_outcome)
    markouts = [row for row in events(read("MARKOUTS.json")["deploy"])
                if row.get("fill_id") == first["fill_id"]]
    settled_ids = {row["window"] for row in settled}
    result = {"scope": raw["scope"], "verification_checks": checks,
              "new_policy_settlements": new,
              "new_policy_traded_windows": sum(row["fills"] > 0 for row in new),
              "zero_fill_windows": sum(row["fills"] == 0 for row in new),
              "new_policy_wins": sum(dec(row["pnl_usd"]) > 0 for row in new),
              "new_policy_wins_usd": amount(sum((dec(row["pnl_usd"]) for row in new
                                                  if dec(row["pnl_usd"]) > 0), Decimal(0))),
              "new_policy_pnl_usd": amount(new_net), "inherited_pnl_usd": amount(inherited),
              "deployment_period_settled_change_usd": amount(total),
              "all_new_fill_fees_usd": amount(all_fees),
              "cash_change_usd": amount(cash_change),
              "cash_arithmetic_scope": "matches settled change plus recorded gross-cost change; not a full cash-flow audit",
              "unsettled_fills_excluded": [row for row in fills if row["window"] not in settled_ids],
              "target": {"window": TARGET, "events": len(target), "intents": len(intents),
                         "ordinary_hedge_intents": sum(row.get("side") == "up" and row["at"] > first["at"]
                                                       and row.get("kind") == "rest" for row in intents),
                         "cancel_reasons": dict(Counter(row["reason"] for row in target
                                                         if row["event"] == "speeddesk_live_cancel")),
                         "first_fill": first, "late_hedge": hedge,
                         "without_only_actual_hedge_same_official_outcome_usd": amount(no_hedge_actual_outcome),
                         "first_fill_markout_gaps": [{"horizon_s": row["horizon_s"], "reason": row.get("reason"),
                                                      "detection_delay_s": row["detection_delay_s"]}
                                                     for row in markouts]},
              "limits": ["Bounded native logs, not raw-volume/account-ledger certification.",
                         "Snapshot counter reconciliation supports this cohort, not whole-day coverage.",
                         "No executable earlier replacement hedge or queue retention gain proved.",
                         "No practice comparison, causal profitability claim, threshold fit or TEST consumption."]}
    (ROOT / "ANALYSIS.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"checks": checks, "new_net": amount(new_net), "deployment_net": amount(total),
                      "money_receipt_sha256": hashlib.sha256((ROOT / "MONEY_LOGS.json").read_bytes()).hexdigest()}))


if __name__ == "__main__":
    main()
