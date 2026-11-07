"""Descriptive public source-wallet audit, not a strategy fit or backtest."""
from __future__ import annotations

import argparse
import calendar
import csv
import json
import math
import re
import statistics
from collections import Counter, defaultdict
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from lucas_history import HISTORY, WALLET

MONTHS = "january|february|march|april|may|june|july|august|september|october|november|december"


def amount(value: Any) -> Decimal:
    out = Decimal(str(value))
    if not out.is_finite():
        raise ValueError("Nonfinite amount")
    return out


def stamp(value: str) -> float:
    return datetime.fromisoformat(value).timestamp()


def month(at: float) -> str:
    return datetime.fromtimestamp(at, UTC).strftime("%Y-%m")


def stats(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {"n": 0, "min": None, "p10": None, "median": None, "p90": None, "max": None}
    ordered = sorted(values)
    return {"n": len(values), "min": ordered[0], "p10": ordered[max(0, math.ceil(.1 * len(values)) - 1)],
            "median": statistics.median(values), "p90": ordered[max(0, math.ceil(.9 * len(values)) - 1)], "max": ordered[-1]}


def trade_key(row: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(row[key] for key in ("timestamp", "side", "token_id", "condition_id", "size", "price", "transaction_hash"))


def reconcile_trades(activity: list[dict[str, Any]], trades: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Match indexed events without concealing share-size disagreements across APIs."""
    fields = ("timestamp", "side", "token_id", "condition_id", "price", "transaction_hash")
    grouped_activity: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    grouped_trades: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in activity:
        if row["type"] == "TRADE":
            grouped_activity[tuple(row[field] for field in fields)].append(row)
    for row in trades:
        grouped_trades[tuple(row[field] for field in fields)].append(row)
    if grouped_activity.keys() != grouped_trades.keys():
        raise ValueError("Activity and trades event identities differ")
    matched, differences = [], []
    for identity, activity_rows in grouped_activity.items():
        trade_rows = grouped_trades[identity].copy()
        if len(trade_rows) != len(activity_rows):
            raise ValueError("Activity and trades event multiplicity differs")
        unmatched = []
        for activity_row in activity_rows:
            exact = next((row for row in trade_rows if amount(row["size"]) == amount(activity_row["size"])), None)
            if exact is None:
                unmatched.append(activity_row)
            else:
                trade_rows.remove(exact)
                matched.append({**activity_row, "all_trades_reported_size": exact["size"], "role_identity": trade_key(exact)})
        if len(unmatched) > 1:
            raise ValueError("Ambiguous cross-endpoint share disagreement")
        for activity_row, trade_row in zip(unmatched, trade_rows, strict=True):
            matched.append({**activity_row, "all_trades_reported_size": trade_row["size"], "role_identity": trade_key(trade_row)})
            differences.append({"transaction_hash": activity_row["transaction_hash"], "timestamp": activity_row["timestamp"],
                                "activity_size": activity_row["size"], "trade_size": trade_row["size"],
                                "price": activity_row["price"], "activity_cash": activity_row["usdc_size"]})
    return sorted(matched, key=lambda row: row["timestamp"]), differences


def rules_expiry(slug: str, market: dict[str, Any]) -> float | None:
    """Monthly Binance rule ends after the month's last one-minute ET candle.

    Older Gamma endDate fields can be 16 or 28 hours early; use the written
    calendar-month rule and disclose current metadata, never realized touch time.
    """
    match = re.search(r"hit-in-(" + MONTHS + r")(?:-|$)", slug)
    description = market.get("description", "")
    if match is None or "Binance" not in description or "ET" not in description:
        return None
    number = MONTHS.split("|").index(match[1]) + 1
    explicit = re.search(r"between ([A-Za-z]+) 1, (20[0-9]{2}), 00:00 and ([A-Za-z]+) ([0-9]+), \2, 23:59", description)
    if explicit:
        year = int(explicit[2])
        if explicit[1].lower() != match[1] or explicit[3].lower() != match[1] or int(explicit[4]) != calendar.monthrange(year, number)[1]:
            return None
        return datetime(year + (number == 12), number % 12 + 1, 1, tzinfo=ZoneInfo("America/New_York")).timestamp()
    modern = "month specified in the title" in description and "11:59 PM ET on the last" in description
    late_start = re.search(r"and ([A-Za-z]+) ([0-9]+) 11:59PM ET", description)
    reference_raw = market.get("endDate") or market.get("_event_end")
    if not (modern or late_start) or not reference_raw:
        return None
    reference = datetime.fromtimestamp(stamp(reference_raw), UTC)
    candidates = [(year, datetime(year + (number == 12), number % 12 + 1, 1, tzinfo=ZoneInfo("America/New_York")))
                  for year in (reference.year - 1, reference.year, reference.year + 1)]
    year, closest = min(candidates, key=lambda value: abs(value[1].timestamp() - reference.timestamp()))
    if abs(closest.timestamp() - reference.timestamp()) >= 32 * 86400:
        return None
    if late_start and (late_start[1].lower() != match[1] or int(late_start[2]) != calendar.monthrange(year, number)[1]):
        return None
    return closest.timestamp()


def classify(row: dict[str, Any], market: dict[str, Any] | None) -> dict[str, Any]:
    slug = row["event_slug"]
    coin = "BTC" if "bitcoin" in slug else "ETH" if "ethereum" in slug else "SOL" if "solana" in slug else None
    monthly = bool(re.search(r"what-price-will-(bitcoin|ethereum|solana)-hit-in-(?:" + MONTHS + r")(?:-|$)", slug))
    core = monthly and coin in {"BTC", "ETH"}
    result: dict[str, Any] = {"coin": coin, "monthly": monthly, "core": core, "direction": None, "strike": None, "expiry": None,
              "no_settlement": None, "resolution_source": None, "metadata_expiry": None, "rule_expiry_verified": False}
    if market is None:
        return result
    match = re.search(r"([↑↓])\s*\$?([\d,.]+)\s*([kK]?)", market.get("groupItemTitle", ""))
    if match:
        result["direction"] = "max" if match[1] == "↑" else "min"
        result["strike"] = float(match[2].replace(",", "")) * (1000 if match[3] else 1)
    if match is None:
        question = re.search(r"(?:reach|dip to) \$([\d,.]+)\s*([kK]?)", market.get("question", ""))
        if question:
            result["direction"] = "min" if "dip to" in question[0] else "max"
            result["strike"] = float(question[1].replace(",", "")) * (1000 if question[2] else 1)
    if market.get("endDate"):
        result["metadata_expiry"] = stamp(market["endDate"])
    if monthly:
        result["expiry"] = rules_expiry(slug, market)
        result["rule_expiry_verified"] = result["expiry"] is not None
    else:
        result["expiry"] = result["metadata_expiry"]
    result["resolution_source"] = market.get("resolutionSource") or ("Binance per description" if "Binance" in market.get("description", "") else "unknown")
    outcomes, prices = json.loads(market.get("outcomes", "[]")), json.loads(market.get("outcomePrices", "[]"))
    by_outcome = dict(zip(outcomes, prices, strict=True))
    if market.get("closed") and market.get("umaResolutionStatus") == "resolved" and str(by_outcome.get("No")) in {"0", "1"}:
        result["no_settlement"] = int(by_outcome["No"])
    return result


def signed_z(spot: float, strike: float, direction: str, days: float, vol: float) -> float | None:
    if not all(math.isfinite(x) for x in (spot, strike, days, vol)) or min(spot, strike, days, vol) <= 0:
        return None
    if direction not in {"max", "min"}:
        return None
    distance = math.log(strike / spot) if direction == "max" else math.log(spot / strike)
    if distance <= 0:
        return None
    return distance / (vol * math.sqrt(days / 365))


def cash_delta(row: dict[str, Any]) -> Decimal | None:
    kind, value = row["type"], amount(row["usdc_size"])
    if kind == "TRADE":
        return value * (1 if row["side"] == "SELL" else -1) if row["side"] in {"BUY", "SELL"} else None
    if kind in {"DEPOSIT", "REDEEM", "MERGE", "YIELD", "MAKER_REBATE", "TAKER_REBATE", "REWARD", "REFERRAL"}:
        return value
    if kind in {"WITHDRAWAL", "SPLIT"}:
        return -value
    return None


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError("Refusing an empty evidence table")
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def analyze(directory: Path, output: Path) -> dict[str, Any]:
    from touch_spot_data import features_at, load_envelopes

    for name in ("activity", "trades", "taker_trades", "tips"):
        manifest = json.loads((directory / name / "manifest.json").read_text())
        if manifest.get("complete") is not True or manifest["params"].get("user") != WALLET:
            raise ValueError("Complete fixed-wallet cursor walks are required")
    activity = list(HISTORY.iter_rows(directory / "activity"))
    reported_trades = list(HISTORY.iter_rows(directory / "trades"))
    fills, size_disagreements = reconcile_trades(activity, reported_trades)
    takers = Counter(trade_key(r) for r in HISTORY.iter_rows(directory / "taker_trades"))
    trade_counter = Counter(trade_key(r) for r in reported_trades)
    if takers - trade_counter:
        raise ValueError("Taker trades are not a subset")
    markets: dict[str, Any] = {}
    for path in sorted((directory / "markets").glob("*.json")):
        for event in json.loads(path.read_text())["response"]:
            for market in event["markets"]:
                market = {**market, "_event_end": event.get("endDate")}
                condition = market["conditionId"]
                if condition in markets and markets[condition] != market:
                    raise ValueError("Conflicting market metadata")
                markets[condition] = market
    candles = {coin: load_envelopes((directory / "candles" / coin).glob("*.json"), product=coin + "-USD") for coin in ("BTC", "ETH")}
    recs = []
    remaining_takers = takers.copy()
    for row in fills:
        record = {**row, **classify(row, markets.get(row["condition_id"]))}
        identity = row["role_identity"]
        record["taker"] = remaining_takers[identity] > 0
        if record["taker"]:
            remaining_takers[identity] -= 1
        record["days_left"] = (record["expiry"] - row["timestamp"]) / 86400 if record["expiry"] else None
        record["z"] = None
        record["feature_reason"] = "outside_btc_eth_monthly_no_buy"
        record["historic_resolution_source_touch_checked"] = False
        if record["core"] and row["side"] == "BUY" and row["outcome"] == "No":
            feature = features_at(candles[record["coin"]], row["timestamp"])
            record["feature_reason"] = feature["reason"] if record["expiry"] is not None else "unknown_rules_expiry"
            if feature["eligible"] and record["strike"] and record["days_left"] is not None:
                record["z"] = signed_z(feature["spot"], record["strike"], record["direction"], record["days_left"], feature["sigma_annual"])
                record["feature_reason"] = "descriptive_proxy_only" if record["z"] is not None else "wrong_side_or_expired"
        recs.append(record)
    core = [r for r in recs if r["core"] and r["side"] == "BUY" and r["outcome"] == "No"]
    core_cash = sum(amount(r["usdc_size"]) for r in core)
    strikes: dict[str, list[dict[str, Any]]] = defaultdict(list)
    ladders: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in core:
        strikes[row["condition_id"]].append(row)
        ladders[row["event_slug"]].append(row)
    strike_rows = []
    for condition, rows in sorted(strikes.items()):
        sales = [r for r in recs if r["condition_id"] == condition and r["side"] == "SELL" and r["outcome"] == "No"]
        buys = sum(amount(r["usdc_size"]) for r in rows)
        sizes = sum(amount(r["size"]) for r in rows)
        unique_times = sorted({r["timestamp"] for r in rows})
        strike_rows.append({"condition_id": condition, "event_slug": rows[0]["event_slug"], "title": rows[0]["title"],
                            "direction": rows[0]["direction"], "strike": rows[0]["strike"], "buy_fills": len(rows),
                            "distinct_buy_block_seconds": len(unique_times), "first_buy_at": unique_times[0], "last_buy_at": unique_times[-1],
                            "buy_cash": float(buys), "bought_shares": float(sizes), "weighted_buy_price": float(buys / sizes),
                            "sold_shares": sum(float(r["size"]) for r in sales), "sell_cash": sum(float(r["usdc_size"]) for r in sales),
                            "no_settlement": rows[0]["no_settlement"], "minimum_descriptive_z": min((r["z"] for r in rows if r["z"] is not None), default=None),
                            "first_buy_days_left": rows[0]["days_left"], "last_buy_days_left": rows[-1]["days_left"]})
    ladder_rows = []
    for event, rows in sorted(ladders.items()):
        conds = {r["condition_id"] for r in rows}
        ladder_rows.append({"event_slug": event, "coin": rows[0]["coin"], "strikes": len(conds),
                            "max_strikes": len({r["condition_id"] for r in rows if r["direction"] == "max"}),
                            "min_strikes": len({r["condition_id"] for r in rows if r["direction"] == "min"}),
                            "buy_fills": len(rows), "buy_cash": sum(float(r["usdc_size"]) for r in rows),
                            "first_buy_at": min(r["timestamp"] for r in rows), "last_buy_at": max(r["timestamp"] for r in rows)})
    pnl_data = json.loads((directory / "pnl-daily.json").read_text())["response"]["data"]
    if pnl_data["proxy_wallet"].lower() != WALLET or pnl_data["source_fidelity"] != "1d":
        raise ValueError("P&L wallet or source fidelity differs")
    pnl = pnl_data["points"]
    legacy = json.loads((directory / "pnl-legacy-daily.json").read_text())["response"]
    cash = json.loads((directory / "cash.json").read_text())
    cash_by_month = {r["month"]: r for r in cash["points"]}
    chart_by_month: dict[str, dict[str, Any]] = {}
    legacy_by_month: dict[str, dict[str, Any]] = {}
    for point in pnl:
        chart_by_month[month(point["timestamp"] - 1)] = point
    for point in legacy:
        legacy_by_month[month(point["t"] - 1)] = point
    months = sorted({month(r["timestamp"]) for r in activity} | set(chart_by_month) | set(cash_by_month))
    monthly = []
    cum_deposits = cum_withdrawals = previous_pnl = previous_legacy = Decimal(0)
    for key in months:
        rows = [r for r in activity if month(r["timestamp"]) == key]
        deposits = sum((amount(r["usdc_size"]) for r in rows if r["type"] == "DEPOSIT"), Decimal(0))
        withdrawals = sum((amount(r["usdc_size"]) for r in rows if r["type"] == "WITHDRAWAL"), Decimal(0))
        cum_deposits += deposits
        cum_withdrawals += withdrawals
        point, legacy_point, balance = chart_by_month.get(key), legacy_by_month.get(key), cash_by_month.get(key)
        current = amount(point["economic_pnl"]) if point else None
        current_legacy = amount(legacy_point["p"]) if legacy_point else None
        block_at = balance["block_at"] if balance else None
        before = [r for r in activity if block_at and r["timestamp"] <= block_at]
        deltas = [cash_delta(r) for r in before]
        implied_cash = sum((d for d in deltas if d is not None), Decimal(0)) if balance else None
        archived_cash = sum((amount(x) for x in balance["balances"].values() if x is not None), Decimal(0)) if balance else None
        monthly.append({"month": key, "deposits_usd": float(deposits), "withdrawals_usd": float(withdrawals),
                        "cumulative_net_external_funding_usd": float(cum_deposits - cum_withdrawals),
                        "provider_economic_pnl_change": float(current - previous_pnl) if current is not None else None,
                        "provider_economic_pnl_cumulative": float(current) if current is not None else None,
                        "legacy_chart_pnl_change": float(current_legacy - previous_legacy) if current_legacy is not None else None,
                        "legacy_chart_pnl_cumulative": float(current_legacy) if current_legacy is not None else None,
                        "provider_series_at": point["timestamp"] if point else None, "source_block": balance["source_block"] if balance else None,
                        "source_block_at": block_at, "provider_source_lag_seconds": point["timestamp"] - block_at if point and block_at else None,
                        "archived_usdc_e": balance["balances"].get("USDC.e") if balance else None,
                        "archived_native_usdc": balance["balances"].get("native USDC") if balance else None,
                        "archived_pusd": balance["balances"].get("pUSD collateral") if balance else None,
                        "activity_cash_before_source_block": float(implied_cash) if implied_cash is not None else None,
                        "activity_minus_archived_cash": float(implied_cash - archived_cash) if implied_cash is not None and archived_cash is not None else None,
                        "unknown_cash_events": sum(d is None for d in deltas),
                        "buy_fills": sum(r["type"] == "TRADE" and r["side"] == "BUY" for r in rows),
                        "sell_fills": sum(r["type"] == "TRADE" and r["side"] == "SELL" for r in rows)})
        if current is not None:
            previous_pnl = current
        if current_legacy is not None:
            previous_legacy = current_legacy
    output.mkdir(parents=True, exist_ok=True)
    write_csv(output / "LUCAS_monthly.csv", monthly)
    write_csv(output / "LUCAS_strikes.csv", strike_rows)
    write_csv(output / "LUCAS_ladders.csv", ladder_rows)
    receipt_map = {row["transaction_hash"]: row for row in cash["funding_receipts"]}
    receipt_disagreements = []
    for row in activity:
        if row["type"] not in {"DEPOSIT", "WITHDRAWAL"}:
            continue
        receipt = receipt_map[row["transaction_hash"]]
        if receipt.get("unavailable"):
            receipt_disagreements.append({"transaction_hash": row["transaction_hash"], "reason": "unavailable"})
            continue
        net = sum((amount(event["amount"]) * (1 if event["wallet_direction"] == "in" else -1 if event["wallet_direction"] == "out" else 0)
                   for event in receipt["cash_token_events"]), Decimal(0))
        expected = amount(row["usdc_size"]) * (1 if row["type"] == "DEPOSIT" else -1)
        if net != expected:
            receipt_disagreements.append({"transaction_hash": row["transaction_hash"], "reported": str(expected), "receipt_cash_net": str(net)})
    valid = [r for r in core if r["z"] is not None]
    resolved = [r for r in strike_rows if r["no_settlement"] is not None]
    def cohort_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
        conditions = {r["condition_id"] for r in rows}
        settled = [r for r in strike_rows if r["condition_id"] in conditions and r["no_settlement"] is not None]
        return {"fills": len(rows), "conditions": len(conditions), "cash": sum(float(r["usdc_size"]) for r in rows),
                "price": stats([float(r["price"]) for r in rows]),
                "z": stats([r["z"] for r in rows if r["z"] is not None]),
                "days_left": stats([r["days_left"] for r in rows if r["days_left"] is not None]),
                "resolved_conditions": len(settled), "winning_no_conditions": sum(r["no_settlement"] == 1 for r in settled),
                "warning": "Descriptive outcome rate, not a simulated execution strategy or after-fee return"}

    def drawdown(points: list[dict[str, Any]], field: str) -> dict[str, float]:
        peak, maximum = 0.0, 0.0
        for point in points:
            peak = max(peak, float(point[field]))
            maximum = max(maximum, peak - float(point[field]))
        return {"drawdown_usd": maximum, "peak_cumulative_pnl": peak,
                "drawdown_divided_by_profit_peak": maximum / peak if peak else 0}

    summary = {"wallet": WALLET, "cutoff": json.loads((directory / "request.json").read_text())["cutoff"],
               "streams": {name: {k: v for k, v in json.loads((directory / name / "manifest.json").read_text()).items() if k != "pages"} for name in ("activity", "trades", "taker_trades", "tips")},
               "full": {"share_disagreements": size_disagreements, "fills": len(fills), "roles": dict(Counter("taker" if r["taker"] else "maker_by_difference" for r in recs)),
                        "sides": dict(Counter(r["side"] + "_" + r["outcome"] for r in recs)), "first_trade": fills[0], "events": len({r["event_slug"] for r in recs})},
               "core": {"scout_price_band_96_to_99": cohort_metrics([r for r in core if .96 <= r["price"] <= .99]),
                        "high_price_at_least_97": cohort_metrics([r for r in core if r["price"] >= .97]),
                        "post_expiry_fills": [r for r in core if r["days_left"] is not None and r["days_left"] < 0],
                        "fills": len(core), "cash": float(core_cash), "ladder_count": len(ladders), "strike_count": len(strikes),
                        "sell_fills": sum(r["core"] and r["side"] == "SELL" for r in recs),
                        "yes_buy_fills": sum(r["core"] and r["side"] == "BUY" and r["outcome"] == "Yes" for r in recs),
                        "maker_fill_share": sum(not r["taker"] for r in core) / len(core),
                        "maker_cash_share": float(sum(amount(r["usdc_size"]) for r in core if not r["taker"]) / core_cash),
                        "cash_at_least_97c_share": float(sum(amount(r["usdc_size"]) for r in core if amount(r["price"]) >= Decimal(".97")) / core_cash),
                        "price": stats([float(r["price"]) for r in core]), "days_left": stats([r["days_left"] for r in core if r["days_left"] is not None]),
                        "fill_shares": stats([float(r["size"]) for r in core]), "fill_cash": stats([float(r["usdc_size"]) for r in core]),
                        "z_descriptive": stats([r["z"] for r in valid]), "feature_reasons": dict(Counter(r["feature_reason"] for r in core)),
                        "direction": dict(Counter(r["direction"] or "unknown" for r in core)),
                        "strike_buy_cash": stats([r["buy_cash"] for r in strike_rows]), "strike_buys": stats([r["buy_fills"] for r in strike_rows]),
                        "strike_add_seconds": stats([float(r["distinct_buy_block_seconds"]) for r in strike_rows]),
                        "ladder_buy_cash": stats([r["buy_cash"] for r in ladder_rows]), "ladder_strikes": stats([float(r["strikes"]) for r in ladder_rows]),
                        "resolved_no_strikes": len(resolved), "resolved_no_wins": sum(r["no_settlement"] == 1 for r in resolved),
                        "losing_strikes": [r for r in resolved if r["no_settlement"] == 0]},
               "daily_grid_drawdowns": {"economic": drawdown(pnl, "economic_pnl"), "legacy": drawdown(legacy, "p")},
               "pnl_latest": pnl[-1], "legacy_latest": legacy[-1], "pnl_points": len(pnl), "legacy_points": len(legacy),
               "funding": {kind: float(sum(amount(r["usdc_size"]) for r in activity if r["type"] == kind)) for kind in ("DEPOSIT", "WITHDRAWAL", "YIELD", "MAKER_REBATE", "TAKER_REBATE", "REWARD")},
               "funding_receipt_differences": receipt_disagreements,
               "first_funding": next(r for r in activity if r["type"] == "DEPOSIT"), "latest_cash": cash["points"][-1]}
    HISTORY.atomic_json(directory / "analysis.json", summary)
    HISTORY.atomic_json(directory / "features.json", recs)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(analyze(args.directory, args.output), indent=2))


if __name__ == "__main__":
    main()
