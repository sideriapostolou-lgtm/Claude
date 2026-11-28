"""Offline verification of bounded PR76 runtime and inherited PR75 settlements."""
from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent
D = Decimal
TOL = D("0.00000001")
DEPLOYMENT = "43f14443-2d07-4985-b879-3a2515fb8d2c"


def main() -> None:
    checks: list[str] = []

    def check(name: str, condition: bool) -> None:
        if not condition:
            raise AssertionError(name)
        checks.append(name)

    def close(name: str, actual: object, expected: Decimal) -> None:
        check(name, abs(D(str(actual)) - expected) < TOL)

    def read(name: str) -> dict:
        return json.loads((ROOT / name).read_text())

    original_receipt = read("MONEY_LOGS.json")
    original = original_receipt["rows"]
    old_deployment = "7582010e-5681-41bb-964b-951e8b3c6767"
    check("original exact PR75 deployment", original_receipt["scope"]["deployment_id"] == old_deployment)
    roll = read("INHERITED_ROLLFORWARD.json")["deploy"]
    new = read("NEXT_WINDOW.json")
    query = new["money_query"]
    money = query["response"]["deploy"]
    expected_filter = " OR ".join('"nightcrawler.speeddesk: speeddesk_live_' + kind + '"'
                                  for kind in ("order", "cancel", "fill", "settlement"))
    check("exact deployment", query["response"]["deploymentId"] == DEPLOYMENT)
    check("all order and money headers queried", query["filter"] == expected_filter)
    start, end = (datetime.fromisoformat(query[k]) for k in ("startDate", "endDate"))
    check("query covers container start", start <= datetime.fromisoformat("2026-10-16T23:50:25Z"))
    check("query covers new window", end >= datetime.fromisoformat("2026-10-17T00:01:00Z"))
    check("query end reached before request", datetime.fromisoformat(new["requested_at_utc"]) >= end)
    check("money query unsaturated", len(money) < query["limit"])
    roll_receipt = read("INHERITED_ROLLFORWARD.json")
    check("roll exact PR75 deployment", roll_receipt["deploymentId"] == old_deployment)
    check("roll query unsaturated", len(roll) < roll_receipt["query"]["limit"])
    check("no new order/cancel/fill headers", all(
        "nightcrawler.speeddesk: speeddesk_live_settlement " in row["message"] for row in money))
    fills: dict[str, dict] = {}
    settlements: dict[str, dict] = {}
    for row in original + roll + money:
        message = row["message"]
        data = json.loads(message[message.index("{"):])
        if "nightcrawler.speeddesk: speeddesk_live_fill " in message:
            key, target = data["fill_id"], fills
        else:
            check("settlement header", "nightcrawler.speeddesk: speeddesk_live_settlement " in message)
            key, target = data["window"], settlements
        check("unique receipt " + key, key not in target)
        target[key] = data
    check("all observed fills predate containment merge", all(f["at"] < 1792194562 for f in fills.values()))

    inherited = "KXBTC15M-26OCT161645-45"
    check("original inherited pair present", inherited in settlements)
    results: list[tuple[str, Decimal, int]] = []
    for window, settlement in settlements.items():
        if window == inherited:
            continue
        rows = [f for f in fills.values() if f["window"] == window]
        cost = sum((D(str(f["price"])) * D(str(f["size"])) for f in rows), D(0))
        fees = sum((D(str(f["fee_usd"])) for f in rows), D(0))
        for side in ("up", "down"):
            size = sum((D(str(f["size"])) for f in rows if f["side"] == side), D(0))
            close(window + " " + side, settlement[side + "_shares"], size)
        payout = D(str(settlement["up_shares" if settlement["up_wins"] else "down_shares"]))
        close(window + " cost", settlement["cost_usd"], cost)
        close(window + " fees", settlement["fee_usd"], fees)
        close(window + " payout", settlement["payout_usd"], payout)
        pnl = payout - cost - fees
        close(window + " pnl", settlement["pnl_usd"], pnl)
        results.append((window, pnl, len(rows)))
    check("every new fill settled", all(f["window"] in settlements for f in fills.values()))

    before = read("PREDEPLOY.json")["samples"][-1]["data"]
    fresh = new["fresh_after_open"]["data"]
    check("native exact deployment", new["native_query"]["response_deployment_id"] == DEPLOYMENT)
    check("opening exact deployment", new["opening_query"]["response"]["deploymentId"] == DEPLOYMENT)
    check("fresh native timestamp covered", start <= datetime.fromisoformat(new["fresh_after_open"]["timestamp"]) <= end)
    check("native selected from saved samples", new["fresh_after_open"] in new["samples"])
    check("opening timestamps covered", all(
        start <= datetime.fromisoformat(row["timestamp"]) <= end for row in new["opening_rows"]))
    check("new window observed", any(
        r["data"].get("venue") == "kalshi"
        and r["data"]["window"] == "KXBTC15M-26OCT162015-15"
        and r["data"]["at"] >= 1792195200 for r in new["opening_rows"]))
    check("fresh native after opening", fresh["at"] > 1792195200)
    check("reduction-only waiting", fresh["waiting"].startswith("REDUCTION ONLY:"))
    check("policy2", fresh["pair_execution"]["version"] == 2)
    check("policy name", fresh["pair_execution"]["policy"] == "reduction_only")
    check("starters disabled", fresh["pair_execution"]["starter"] == "disabled")
    check("no automatic resume", fresh["pair_execution"]["automatic_resume"] is False)
    check("no automatic expiry", fresh["pair_execution"]["expires_at"] is None)
    check("successful recent reconcile", fresh["reconcile"]["last"]["failed"] is False
          and fresh["reconcile"]["last"]["checks"] == {})
    check("live authenticated, not entering", fresh["mode"] == "live"
          and fresh["authenticated"] is True and fresh["trading_now"] is False)
    for key in ("caps", "cash_usd", "total_halted", "day_stop_latched", "integrity_error"):
        check("retained " + key, fresh[key] == before[key])
    for key in ("open_risk_usd", "reserved_usd", "open_orders", "open_cost_usd"):
        close("flat " + key, fresh[key], D(0))
    for key in ("fills", "fees_usd", "maker_orders", "take_attempts", "locks"):
        check("no new " + key, fresh["total"][key] == before["total"][key])
    check("one new-deployment settlement row", len(money) == 1)
    new_settlement = json.loads(money[0]["message"][money[0]["message"].index("{"):])
    check("new-deployment settlement is inherited", new_settlement["window"] == "KXBTC15M-26OCT162000-00")
    check("settlement count", fresh["total"]["settled_windows"] == before["total"]["settled_windows"] + 1)
    close("inherited result", settlements["KXBTC15M-26OCT162000-00"]["pnl_usd"], D("0.0127"))
    close("cumulative roll-forward", fresh["total"]["pnl_usd"], D(str(before["total"]["pnl_usd"])) + D("0.0127"))
    wins = [pnl for _, pnl, count in results if count and pnl > 0]
    net = sum((pnl for _, pnl, _ in results), D(0))
    out = {"checks": len(checks), "check_names": checks,
           "scope": "Bounded actual receipt reconciliation, not profitability or complete account certification",
           "pr75_traded_settled_windows": sum(count > 0 for _, _, count in results),
           "pr75_zero_fill_settlements": sum(count == 0 for _, _, count in results),
           "pr75_wins": len(wins), "pr75_wins_usd": str(sum(wins, D(0))),
           "pr75_new_settled_net_usd": str(net),
           "pr76_new_order_fill_rows": 0, "pr76_inherited_settlement_usd": "0.0127",
           "pr76_new_strategy_profit": "not established; no new trades",
           "final_native_timestamp": new["fresh_after_open"]["timestamp"]}
    (ROOT / "RUNTIME_VERIFICATION.json").write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps({key: value for key, value in out.items() if key != "check_names"}, indent=2))


if __name__ == "__main__":
    main()
