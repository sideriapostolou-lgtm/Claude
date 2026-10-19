"""Offline, fixed-fill diagnosis; never creates alternative fills or opens TEST data."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
DAY = "research/daily_status_2026-10-17/"
POST = "research/kalshi_post75_loss_2026-10-16/"
OLD = "research/kalshi_loss_cause_2026-10-16/"
SOURCES = {}
CHECKS = 0


def read(name):
    data = (REPO / name).read_bytes()
    SOURCES[name] = hashlib.sha256(data).hexdigest()
    return json.loads(data)


def check(value):
    global CHECKS
    assert value
    CHECKS += 1


def dec(value):
    return Decimal(str(value))


def close(left, right):
    check(abs(dec(left) - dec(right)) < Decimal("0.00000001"))


def events(rows):
    result = []
    for row in rows:
        match = re.search(r"nightcrawler\.speeddesk: (\w+) (\{.*\})$", row["message"])
        if match:
            result.append({"event": match[1], **json.loads(match[2])})
    return result


def summed(rows, key):
    return sum((dec(row[key]) for row in rows), Decimal(0))


def payoff(fills, up_wins):
    return sum((dec(f["size"]) * (int((f["side"] == "up") == up_wins)
                - dec(f["price"])) - dec(f["fee_usd"]) for f in fills), Decimal(0))


def main():
    raw = read(DAY + "DAY_MONEY_LOGS.json")
    check(len(raw["response"]["deploy"]) < raw["request"]["limit"])
    money = events(raw["response"]["deploy"])
    fills = [r for r in money if r["event"] == "speeddesk_live_fill"]
    settlements = [r for r in money if r["event"] == "speeddesk_live_settlement"]
    check(len({f["fill_id"] for f in fills}) == len(fills) == 149)
    check(len({s["settlement_id"] for s in settlements}) == len(settlements) == 60)
    by_window = defaultdict(list)
    for fill in fills:
        by_window[fill["window"]].append(fill)

    # These captures were selected in earlier loss investigations. They cannot
    # become an unbiased calibration sample just because their joins are exact.
    orders = []
    for name in (OLD + "orders_1700.json", OLD + "orders_1730.json"):
        capture = read(name)
        check(capture["limit_hit"] is False)
        orders += events(capture["rows"])
    for name in (POST + "TARGET_ORDERS.json", POST + "TARGET_START.json"):
        orders += events(read(name)["deploy"])
    intents = {}
    for order in orders:
        if order["event"] == "speeddesk_live_order" and order.get("state") == "durable intent":
            key = order["client_order_id"]
            if key in intents:
                check(intents[key] == order)
            intents[key] = order

    table = []
    for settlement in settlements:
        fs = sorted(by_window[settlement["window"]], key=lambda f: (f["at"], f["fill_id"]))
        for side in ("up", "down"):
            close(sum((dec(f["size"]) for f in fs if f["side"] == side), Decimal(0)),
                  settlement[side + "_shares"])
        cost = sum((dec(f["size"]) * dec(f["price"]) for f in fs), Decimal(0))
        close(cost, settlement["cost_usd"])
        close(summed(fs, "fee_usd"), settlement["fee_usd"])
        close(payoff(fs, settlement["up_wins"]), settlement["pnl_usd"])
        close(dec(settlement["locked_usd"]) + dec(settlement["direction_usd"]),
              settlement["pnl_usd"])
        if not fs:
            check(dec(settlement["pnl_usd"]) == 0)
            continue
        first = fs[0]
        # Group by the earliest filled venue order, not an arbitrary partial
        # receipt. Later partials of that same order remain in the first order.
        first_order = [f for f in fs if f["order_id"] == first["order_id"]]
        check(all(f["side"] == first["side"] for f in first_order))
        check(all(f["client_order_id"] == first["client_order_id"] for f in first_order))
        first_pnl = payoff(first_order, settlement["up_wins"])
        later = [f for f in fs if f["order_id"] != first["order_id"]]
        later_pnl = payoff(later, settlement["up_wins"])
        close(first_pnl + later_pnl, settlement["pnl_usd"])
        quantity = summed(first_order, "size")
        intent = intents.get(first["client_order_id"])
        joined = None
        if intent:
            check(intent["at"] <= first["at"])
            check(intent["window"] == first["window"] and intent["side"] == first["side"])
            check(dec(first["price"]) <= dec(intent["price"]))
            joined = {key: intent[key] for key in ("at", "side", "kind", "price", "size", "fair")}
            joined["quoted_model_edge"] = dec(intent["fair"]) - dec(intent["price"])
            joined["decision_to_first_fill_s"] = first["at"] - intent["at"]
        opposite = [f for f in fs if f["side"] != first["side"]]
        table.append({"window": settlement["window"], "fill_count": len(fs),
                      "balanced_at_settlement": settlement["up_shares"] == settlement["down_shares"],
                      "up_wins": settlement["up_wins"], "pnl_usd": dec(settlement["pnl_usd"]),
                      "first_order_id": first["order_id"], "first_client_order_id": first["client_order_id"],
                      "first_order_fill_ids": [f["fill_id"] for f in first_order],
                      "first_fill_at": first["at"], "first_side": first["side"],
                      "first_order_quantity": quantity, "first_order_fee_usd": summed(first_order, "fee_usd"),
                      "first_order_settlement_cashflow_usd": first_pnl,
                      "first_order_per_contract_cashflow_usd": first_pnl / quantity,
                      "all_other_fill_settlement_cashflow_usd": later_pnl,
                      "first_opposite_fill_delay_s": opposite[0]["at"] - first["at"] if opposite else None,
                      "predecision_intent": joined})

    native = read(DAY + "PRIOR_UTC_DAY_NATIVE.json")["report"]["real"]
    close(summed(table, "pnl_usd"), native["pnl_usd"])
    close(summed(settlements, "locked_usd"), native["locked_usd"])
    close(summed(settlements, "direction_usd"), native["directional_usd"])
    close(summed(table, "first_order_settlement_cashflow_usd"), "-16.3428")
    close(summed(table, "all_other_fill_settlement_cashflow_usd"), "8.1730")
    close(summed(table, "first_order_per_contract_cashflow_usd"), "-2.81")
    check(len(table) == 55)
    check(sum(r["first_order_settlement_cashflow_usd"] > 0 for r in table) == 24)
    empty = [s["window"] for s in settlements if not by_window[s["window"]]]
    check(len(empty) == 5)
    carry = events(read(POST + "NEXT_WINDOW.json")["money_query"]["response"]["deploy"])[0]
    carry_fills = by_window[carry["window"]]
    close(payoff(carry_fills, carry["up_wins"]), carry["pnl_usd"])
    close(carry["pnl_usd"], ".0127")
    excluded = [f for f in fills if f["window"] not in {s["window"] for s in settlements}]
    check(excluded == carry_fills)
    close(summed(fills, "fee_usd") - summed(settlements, "fee_usd"), carry["fee_usd"])

    pr75_start = "KXBTC15M-26OCT161700-00"
    pr75 = [r for r in table if r["window"] >= pr75_start]
    pr75_pnl = [r["pnl_usd"] for r in pr75] + [dec(carry["pnl_usd"])]
    check(len(pr75_pnl) == 11)
    close(sum(pr75_pnl), "-.2674")
    close(sum(p for p in pr75_pnl if p > 0), ".1544")
    close(sum(p for p in pr75_pnl if p < 0), "-.4218")

    target = "KXBTC15M-26OCT161815-15"
    target_orders = {json.dumps(o, sort_keys=True): o for o in orders if o.get("window") == target}
    target_intents = [o for o in target_orders.values()
                      if o["event"] == "speeddesk_live_order" and o.get("state") == "durable intent"]
    target_row = next(r for r in table if r["window"] == target)
    target_first = next(f for f in fills if f["fill_id"] == target_row["first_order_fill_ids"][0])
    hedges = [o for o in target_intents if o["side"] != target_first["side"]
              and o["at"] > target_first["at"] and o["kind"] == "rest"]
    check(len(hedges) == 39)
    check(min(o["at"] for o in hedges) > target_first["at"])
    marks = events(read(POST + "MARKOUTS.json")["deploy"])
    target_marks = [m for m in marks if m.get("fill_id") == target_first["fill_id"]]
    check(len(target_marks) == 3)
    check(all(m["event"] == "speeddesk_fill_markout_gap" for m in target_marks))
    check(all(m["hypothetical_net_usd"] is None for m in target_marks))
    queues = [o for o in target_orders.values() if o["event"] == "speeddesk_live_queue"]
    zeros = [q for q in queues if q.get("queue_position_fp") == "0.00"]
    check(len(zeros) == 2)
    check(all(q["dispatch"]["side"] == "up" for q in zeros))

    partitions = {}
    for balanced in (True, False):
        part = [r for r in table if r["balanced_at_settlement"] == balanced]
        partitions[str(balanced)] = {"windows": len(part), "pnl_usd": summed(part, "pnl_usd"),
                                    "warning": "POST-OUTCOME DIAGNOSTIC; never an entry filter"}
    result = {
        "scope": "Historical development/diagnosis, actual fills only; no untouched test or strategy profit claim",
        "source_sha256": SOURCES,
        "checks_passed": CHECKS,
        "day": "2026-10-16 UTC settlement-day cohort",
        "summary": {"fill_receipts": len(fills), "settled_traded_windows": len(table),
                    "empty_settlements": len(empty), "net_pnl_usd": summed(table, "pnl_usd"),
                    "locked_usd": summed(settlements, "locked_usd"),
                    "directional_usd": summed(settlements, "direction_usd"),
                    "first_order_cashflow_usd": summed(table, "first_order_settlement_cashflow_usd"),
                    "later_fill_cashflow_usd": summed(table, "all_other_fill_settlement_cashflow_usd"),
                    "first_order_equal_window_per_contract_sum_usd": summed(table, "first_order_per_contract_cashflow_usd"),
                    "first_side_outcome_wins": 24, "first_side_outcome_losses": 31,
                    "exact_predecision_intent_joins": sum(r["predecision_intent"] is not None for r in table),
                    "warning": "First-order/later-fill split is fixed-receipt cashflow attribution, not two executable strategies"},
        "post_outcome_partitions": partitions,
        "pr75_complete_cohort": {"windows": len(pr75_pnl), "net_pnl_usd": sum(pr75_pnl),
                                 "wins_usd": sum(p for p in pr75_pnl if p > 0),
                                 "losses_usd": sum(p for p in pr75_pnl if p < 0)},
        "excluded_settlement_day_carry": {"window": carry["window"], "fill_ids": [f["fill_id"] for f in carry_fills],
                                          "next_day_pnl_usd": dec(carry["pnl_usd"]),
                                          "reason": "Settled October17 UTC; PR75 inherited into PR76"},
        "target": {"window": target, "ordinary_opposite_intents": len(hedges),
                   "opposite_price_counts": dict(Counter(str(o["price"]) for o in hedges)),
                   "first_opposite_intent_delay_s": min(o["at"] for o in hedges) - target_first["at"],
                   "zero_queue_samples_on_unfilled_hedge": len(zeros),
                   "zero_queue_is_fill_evidence": False,
                   "first_fill_markout_gaps": [{k: m[k] for k in ("horizon_s", "reason", "detection_delay_s")}
                                               for m in target_marks]},
        "empty_settlement_windows": empty,
        "per_window": table,
        "limitations": ["Observed money log receipts reconcile; provider/raw-volume completeness not certified.",
                        "Whole day mixes source versions, pauses and caps; no causal before/after claim.",
                        "Selected historical intent joins cannot estimate calibration or an entry-gate edge.",
                        "Settlement-balanced cohorts use future information and cannot select entries.",
                        "No alternate fill, exit, cancellation success or missing markout is imputed.",
                        "Public quote alone does not establish queue priority, depth survival or achievable hedge.",
                        "No sealed Family A TEST, network, production mutation or rule/cap change."]}
    output = json.dumps(result, indent=2, default=lambda x: str(x)) + "\n"
    (HERE / "LOSS_MECHANISM.json").write_text(output)
    print(json.dumps({"checks_passed": CHECKS, **result["summary"]}, default=str, indent=2))


if __name__ == "__main__":
    main()
