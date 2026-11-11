"""Reconcile saved real receipts only; no network, strategy fitting or TEST data."""
import hashlib
import json
import re
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent
D = Decimal
ZERO = D(0)
checks = 0


def check(condition, message):
    global checks
    checks += 1
    if not condition:
        raise AssertionError(message)


def read_events(name, event):
    raw = json.loads((ROOT / name).read_text())
    check(not raw["limit_hit"], f"saturated {name}")
    rows = []
    for row in raw["rows"]:
        match = re.search(r"nightcrawler\.speeddesk: " + event + r" (\{.*\})$", row["message"])
        check(match is not None, f"not standalone {name}")
        record = json.loads(match[1], parse_float=D, parse_int=D)
        rows.append(record)
    return rows


def unique(rows, key):
    seen = {}
    for row in rows:
        identity = row[key]
        check(identity not in seen or seen[identity] == row, f"conflicting {identity}")
        seen[identity] = row
    return list(seen.values())


def near(a, b, label):
    check(abs(a - b) < D("0.000000001"), label)


def summary(rows):
    out = {"settlements": len(rows)}
    for key in ("cost_usd", "fee_usd", "payout_usd", "pnl_usd", "locked_usd", "direction_usd"):
        out[key] = sum((r[key] for r in rows), ZERO)
    out["gross_before_fees_usd"] = out["pnl_usd"] + out["fee_usd"]
    out["wins"] = sum(r["pnl_usd"] > D("0.000000001") for r in rows)
    out["losses"] = sum(r["pnl_usd"] < D("-0.000000001") for r in rows)
    return out


settlements = unique(read_events("settlements.json", "speeddesk_live_settlement"), "settlement_id")
fills = unique(read_events("fills.json", "speeddesk_live_fill"), "fill_id")
orders = read_events("orders_1700.json", "speeddesk_live_order") + read_events("orders_1730.json", "speeddesk_live_order")
by_window = defaultdict(list)
for fill in fills:
    by_window[fill["window"]].append(fill)
settled = {row["window"] for row in settlements}
inherited, matched_windows = [], []
for row in settlements:
    window = row["window"]
    near(row["payout_usd"] - row["cost_usd"] - row["fee_usd"], row["pnl_usd"], window + " P&L")
    near(row["locked_usd"] + row["direction_usd"], row["pnl_usd"], window + " split")
    expected_payout = row["up_shares"] if row["up_wins"] else row["down_shares"]
    near(expected_payout, row["payout_usd"], window + " winning shares")
    fs = by_window.get(window, [])
    if not fs and row["cost_usd"]:
        inherited.append(window)
        continue
    for side in ("up", "down"):
        near(sum((f["size"] for f in fs if f["side"] == side), ZERO), row[side + "_shares"], window + side)
    near(sum((f["size"] * f["price"] for f in fs), ZERO), row["cost_usd"], window + " fill cost")
    near(sum((f["fee_usd"] for f in fs), ZERO), row["fee_usd"], window + " fill fees")
    matched_windows.append(window)

status = json.loads((ROOT / "STATUS_PROJECTION.json").read_text(), parse_float=D, parse_int=D)
total = summary(settlements)
today = status["fields"]["today"]
near(total["pnl_usd"], today["pnl_usd"], "status day P&L")
near(total["locked_usd"], today["locked_usd"], "status day locked")
near(total["direction_usd"], today["directional_usd"], "status day directional")
near(total["fee_usd"], today["fees_usd"], "status fees")
check(len(settlements) == today["settled_windows"], "status settlements")
check(len(fills) == today["fills"], "status fills")

examples = []
for suffix in ("1315-15", "1345-45", "1400-00"):
    window = "KXBTC15M-26OCT16" + suffix
    row = next(s for s in settlements if s["window"] == window)
    fs = by_window[window]
    joins = []
    for fill in fs:
        intents = [o for o in orders if o["client_order_id"] == fill["client_order_id"] and o["state"] == "durable intent"]
        acks = [o for o in orders if o["client_order_id"] == fill["client_order_id"] and o["state"] == "accepted; waiting for real fills"]
        check(len(intents) == len(acks) == 1, "exact join " + window)
        intent, ack = intents[0], acks[0]
        check(intent["side"] == fill["side"] and intent["window"] == window, "intent identity")
        check(ack["order_id"] == fill["order_id"], "ack identity")
        check(fill["is_taker"] is False and fill["fee_usd"] == 0, "maker fee")
        joins.append({"fill": fill, "intent": intent, "ack": ack})
    opposite = "down" if fs[0]["side"] == "up" else "up"
    opposite_intents = [o for o in orders if o.get("window") == window and o.get("side") == opposite and o["state"] == "durable intent"]
    examples.append({"window": window, "settlement": row, "joins": joins, "opposite_intents_not_fills": len(opposite_intents)})

result = {
    "scope": "Observed Oct16UTC native publication-day receipts through19:22UTC query; snapshot19:20:25UTC. Retrospective development diagnosis, not a policy backtest or full-account coverage certificate.",
    "checks_passed": checks,
    "unique_fills": len(fills),
    "settlements_reconciled_to_day_fills": len(matched_windows),
    "settlements_without_day_fills": inherited,
    "unsettled_fill_windows": sorted(set(by_window) - settled),
    "day": total,
    "balanced_at_settlement": summary([s for s in settlements if s["up_shares"] == s["down_shares"]]),
    "unequal_at_settlement": summary([s for s in settlements if s["up_shares"] != s["down_shares"]]),
    "settled_since_8am_PDT_mixed_sources_and_caps": summary([s for s in settlements if s["at"] >= D("1792162800")]),
    "settled_since_10am_PDT_not_randomized": summary([s for s in settlements if s["at"] >= D("1792170000")]),
    "three_recent_unpaired_losses": examples,
    "input_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in ROOT.glob("*.json") if p.name in ("settlements.json", "fills.json", "orders_1700.json", "orders_1730.json", "STATUS_PROJECTION.json")},
}
(ROOT / "AUDIT.json").write_text(json.dumps(result, indent=2, default=str) + "\n")
print(json.dumps({"checks_passed": checks, "day": total, "inherited": inherited, "unsettled": result["unsettled_fill_windows"]}, default=str, indent=2))
