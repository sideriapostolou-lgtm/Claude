"""Descriptive accounting of downloaded public history, never a strategy fit."""

from __future__ import annotations

import csv
import json
import math
import re
import statistics
from bisect import bisect_left
from collections import Counter, defaultdict
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from history import WALLET, digest, iter_rows


def day(at: float) -> str:
    return datetime.fromtimestamp(at, UTC).date().isoformat()


def amount(value: Any) -> Decimal:
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError("Nonfinite history amount")
    return result


def clean(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {key: clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(item) for item in value]
    return value


def stats(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {"n": 0, "median": None, "mean": None, "p90": None, "max": None}
    ordered = sorted(values)
    return {"n": len(values), "median": statistics.median(ordered),
            "mean": statistics.mean(ordered), "p90": ordered[max(0, math.ceil(.9 * len(ordered)) - 1)],
            "max": ordered[-1]}


def pnl_deltas(points: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Cumulative provider economics are differenced once; fees stay disclosure.

    Null is unknown. The initial point is inception-to-first-observation, not a
    fabricated full day; the final non-midnight observation is a partial day.
    """
    fields = ("realized_pnl", "unrealized_pnl", "position_pnl", "economic_pnl", "wallet_income",
              "settled_pnl", "trade_pnl", "fees", "maker_rebate", "taker_rebate", "reward_income")
    rows: list[dict[str, Any]] = []
    prior: dict[str, Any] | None = None
    peak, peak_at, worst_drawdown, worst_at, drawdown_peak_at = Decimal(0), None, Decimal(0), None, None
    previous_at = -1
    for point in points:
        at = point["timestamp"]
        if type(at) is not int or at <= previous_at:
            raise ValueError("P&L points must be strictly chronological")
        previous_at = at
        complete = prior is not None and at % 86400 == 0 and at - prior["timestamp"] == 86400
        row: dict[str, Any] = {"day": day(at - 1 if at % 86400 == 0 else at), "start_at": prior["timestamp"] if prior else None,
               "end_at": at, "complete_grid_day": complete, "first_inception_interval": prior is None,
               "source_block": point.get("source_block")}
        for field in fields:
            current = point.get(field)
            previous = prior.get(field) if prior else 0
            row[field + "_change"] = amount(current) - amount(previous) if current is not None and previous is not None else None
        row["economic_pnl_cumulative"] = point.get("economic_pnl")
        row["unrealized_pnl_at_end"] = point.get("unrealized_pnl")
        economic = point.get("economic_pnl")
        if economic is not None:
            value = amount(economic)
            if value > peak:
                peak, peak_at = value, at
            if value - peak < worst_drawdown:
                worst_drawdown, worst_at, drawdown_peak_at = value - peak, at, peak_at
        rows.append(row)
        prior = point
    full = [row for row in rows if row["complete_grid_day"] and row["economic_pnl_change"] is not None]
    worst = min(full, key=lambda row: row["economic_pnl_change"]) if full else None
    return rows, {"worst_reported_grid_day": worst, "daily_grid_max_drawdown": -worst_drawdown,
                  "drawdown_peak_at": drawdown_peak_at, "drawdown_trough_at": worst_at,
                  "intraday_drawdown": None,
                  "limitation": "Unreconciled provider grid changes; source blocks can precede grid timestamps. Not exact UTC-day profit, bankroll equity or intraday risk"}


def activity_cash_delta(row: dict[str, Any]) -> tuple[str, Decimal | None]:
    """Signed reported activity cash; never call buys-minus-deposits profit."""
    kind = row["type"]
    value = amount(row["size"] if kind == "TIP" else row["usdc_size"])
    if value < 0:
        raise ValueError("Unexpected negative activity cash magnitude")
    if kind == "TRADE":
        if row["side"] == "BUY":
            return "trading_cash", -value
        if row["side"] == "SELL":
            return "trading_cash", value
        return "unknown", None
    if kind in {"REDEEM", "MERGE"}:
        return "trading_cash", value
    if kind == "SPLIT":
        return "trading_cash", -value
    if kind == "DEPOSIT":
        return "external_funding", value
    if kind == "WITHDRAWAL":
        return "external_funding", -value
    if kind in {"MAKER_REBATE", "TAKER_REBATE", "REWARD", "YIELD", "REFERRAL"}:
        return "income", value
    if kind == "TIP" and row.get("side") in {"IN", "OUT"}:
        return "external_funding", value if row["side"] == "IN" else -value
    return "unknown", None


def window_metrics(windows: list[dict[str, Any]]) -> dict[str, Any]:
    both = [window for window in windows if window["up_shares"] > 0 and window["down_shares"] > 0]
    return {"windows": len(windows), "both_outcomes": len(both),
            "both_outcomes_fraction": len(both) / len(windows) if windows else None,
            "buy_cash_over_100_windows": sum(w["buy_cash"] > 100 for w in windows),
            "buy_cash_per_window": stats([float(w["buy_cash"]) for w in windows]),
            "fills_per_window": stats([w["fills"] for w in windows]),
            "share_imbalance": stats([abs(float(w["up_shares"] - w["down_shares"])) /
                                      float(w["up_shares"] + w["down_shares"]) for w in windows]),
            "pair_purchase_cash": stats([float(w["up_cash"] / w["up_shares"] +
                                                   w["down_cash"] / w["down_shares"]) for w in both]),
            "pair_cash_below_one_fraction": sum(w["up_cash"] / w["up_shares"] +
                                                  w["down_cash"] / w["down_shares"] < 1 for w in both) / len(both) if both else None}


def summarize(directory: Path) -> dict[str, Any]:
    request = json.loads((directory / "request.json").read_text())
    pnl = json.loads((directory / "pnl-daily.json").read_text())
    data = pnl["response"]["data"]
    if data["proxy_wallet"].lower() != WALLET or data["source_fidelity"] != "1d":
        raise ValueError("Unexpected P&L identity or historical fidelity")
    pnl_end = data["points"][-1]["timestamp"]
    balances_path = directory / "balances/balances.json"
    balances = json.loads(balances_path.read_text()) if balances_path.exists() else None
    if balances is not None and (balances["wallet"] != WALLET
                                 or balances["pnl_sha256"] != digest((directory / "pnl-daily.json").read_bytes())):
        raise ValueError("Archived cash snapshot inputs differ")
    cash_points = {point["source_block"]: point for point in balances["points"]} if balances else {}
    cash_times = sorted({point["block_at"] for point in cash_points.values()})
    cash_buckets = [Decimal(0) for _ in cash_times]
    unknown_buckets = [0 for _ in cash_times]
    coverage = {}
    for name in ("activity", "tips", "trades", "taker_trades"):
        path = directory / name / "manifest.json"
        if not path.exists():
            coverage[name] = {"complete": False, "reason": "not collected"}
            continue
        raw = path.read_bytes()
        manifest = json.loads(raw)
        coverage[name] = {"complete": manifest["complete"], "rows": manifest["rows"],
                          "query": manifest["params"],
                          "pages": len(manifest["pages"]), "manifest_sha256": digest(raw),
                          "retry_events": len(manifest["retries"]),
                          "first_at": min((p["first_at"] for p in manifest["pages"] if p["first_at"]), default=None),
                          "last_at": max((p["last_at"] for p in manifest["pages"] if p["last_at"]), default=None)}
    if not all(coverage[name].get("complete") for name in ("activity", "tips")):
        raise ValueError("Full activity and opt-in TIP walks required before history accounting")

    def empty_day() -> dict[str, Any]:
        return {
        "events": 0, "buy_fills": 0, "sell_fills": 0, "buy_cash": Decimal(0), "sell_cash": Decimal(0),
        "deposits": Decimal(0), "withdrawals": Decimal(0), "redemptions": Decimal(0),
        "trading_cash": Decimal(0), "external_funding": Decimal(0), "income": Decimal(0), "unknown_cash_events": 0}

    daily: dict[str, dict[str, Any]] = defaultdict(empty_day)
    after_pnl: dict[str, dict[str, Any]] = defaultdict(empty_day)
    types: Counter[str] = Counter()
    slugs: Counter[str] = Counter()
    window_map: dict[str, dict[str, Any]] = {}
    cash_by_type: dict[str, Decimal] = defaultdict(Decimal)
    first_event = first_trade = None
    funding = []
    sizes, fill_cash = [], []
    identical_rows: Counter[str] = Counter()
    activity_trade_keys: Counter[tuple[Any, ...]] = Counter()
    def all_activity():
        for stream in ("activity", "tips"):
            for row in iter_rows(directory / stream):
                if (row["type"] == "TIP") != (stream == "tips"):
                    raise ValueError("TIP stream no longer disjoint from default activity")
                yield row

    for row in all_activity():
        stamp, kind = row["timestamp"], row["type"]
        if first_event is None or stamp < first_event["timestamp"]:
            first_event = row
        types[kind] += 1
        cash_by_type[kind] += amount(row["size"] if kind == "TIP" else row["usdc_size"])
        d = (daily if stamp <= pnl_end else after_pnl)[day(stamp)]
        d["events"] += 1
        bucket, delta = activity_cash_delta(row)
        cash_index = bisect_left(cash_times, stamp)
        if cash_index < len(cash_times):
            if delta is None:
                unknown_buckets[cash_index] += 1
            else:
                cash_buckets[cash_index] += delta
        if delta is None:
            d["unknown_cash_events"] += 1
        else:
            d[bucket] += delta
        if kind in {"DEPOSIT", "WITHDRAWAL"}:
            d["deposits" if kind == "DEPOSIT" else "withdrawals"] += amount(row["usdc_size"])
            funding.append({key: row[key] for key in ("timestamp", "type", "usdc_size", "transaction_hash")})
        if kind == "REDEEM":
            d["redemptions"] += amount(row["usdc_size"])
        if kind != "TRADE":
            continue
        if first_trade is None or stamp < first_trade["timestamp"]:
            first_trade = row
        if amount(row["size"]) <= 0 or not 0 <= amount(row["price"]) <= 1:
            raise ValueError("Invalid trade size or price")
        key = tuple(row[field] for field in ("timestamp", "side", "token_id", "condition_id", "size", "price", "transaction_hash"))
        activity_trade_keys[key] += 1
        identical_rows[row["history_row_id"].rsplit(":", 1)[0]] += 1
        slug = row.get("slug", "")
        match = re.fullmatch(r"btc-updown-5m-([0-9]{10})", slug)
        family = re.fullmatch(r"([a-z]+)-updown-5m-[0-9]{10}", slug)
        slugs[family.group(1) + "_5m" if family else slug or "unenriched"] += 1
        if row["side"] not in {"BUY", "SELL"}:
            raise ValueError("Unknown trade action")
        buy = row["side"] == "BUY"
        d["buy_fills" if buy else "sell_fills"] += 1
        d["buy_cash" if buy else "sell_cash"] += amount(row["usdc_size"])
        sizes.append(float(row["size"]))
        fill_cash.append(float(row["usdc_size"]))
        if not match or not buy:
            continue
        start = int(match.group(1))
        window = window_map.setdefault(row["condition_id"], {
            "condition_id": row["condition_id"], "slug": slug, "start": start, "end": start + 300,
            "day": day(start), "fills": 0, "buy_cash": Decimal(0),
            "up_shares": Decimal(0), "down_shares": Decimal(0), "up_cash": Decimal(0), "down_cash": Decimal(0)})
        side = row["outcome"].lower()
        if side not in {"up", "down"}:
            raise ValueError("Unverified five-minute outcome label")
        window["fills"] += 1
        window["buy_cash"] += amount(row["usdc_size"])
        window[side + "_shares"] += amount(row["size"])
        window[side + "_cash"] += amount(row["usdc_size"])
    trade_crosscheck: dict[str, Any] = {"complete": False}
    all_keys: Counter[tuple[Any, ...]] = Counter()
    if coverage["trades"].get("complete"):
        for row in iter_rows(directory / "trades"):
            key = tuple(row[field] for field in ("timestamp", "side", "token_id", "condition_id", "size", "price", "transaction_hash"))
            all_keys[key] += 1
        trade_crosscheck = {"complete": True, "activity_trade_rows": sum(activity_trade_keys.values()),
                            "trade_rows": sum(all_keys.values()),
                            "activity_only_rows": sum((activity_trade_keys - all_keys).values()),
                            "trades_only_rows": sum((all_keys - activity_trade_keys).values())}
    roles: dict[str, Any] = {"known": False}
    if coverage["trades"].get("complete") and coverage["taker_trades"].get("complete"):
        taker_keys: Counter[tuple[Any, ...]] = Counter()
        for row in iter_rows(directory / "taker_trades"):
            key = tuple(row[field] for field in ("timestamp", "side", "token_id", "condition_id", "size", "price", "transaction_hash"))
            taker_keys[key] += 1
        unmatched = sum((taker_keys - all_keys).values())
        total, takers = sum(all_keys.values()), sum(taker_keys.values())
        roles = {"known": unmatched == 0, "all_rows": total, "taker_rows": takers,
                 "taker_rows_not_in_all": unmatched, "maker_rows": total - takers if unmatched == 0 else None,
                 "taker_fill_share": takers / total if unmatched == 0 and total else None,
                 "source": "Official taker_only=true cohort, reconciled as an economic multiset against false"}
        monthly_all: Counter[str] = Counter()
        monthly_taker: Counter[str] = Counter()
        for key, count in all_keys.items():
            monthly_all[day(key[0])[:7]] += count
        for key, count in taker_keys.items():
            monthly_taker[day(key[0])[:7]] += count
        roles["monthly"] = {month: {"all_rows": count, "taker_rows": monthly_taker[month],
                                     "taker_fill_share": monthly_taker[month] / count if unmatched == 0 else None}
                            for month, count in sorted(monthly_all.items())}
    windows = [window for window in window_map.values() if window["end"] <= request["cutoff"]]
    month_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for window in windows:
        month_groups[window["day"][:7]].append(window)
    daily_window_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for window in windows:
        daily_window_groups[window["day"]].append(window)
    pnl_rows, risk = pnl_deltas(data["points"])
    cash_at_source: dict[int, Decimal | None] = {}
    cumulative_cash, cumulative_unknown = Decimal(0), 0
    for source_at, delta, unknown in zip(cash_times, cash_buckets, unknown_buckets, strict=True):
        cumulative_cash += delta
        cumulative_unknown += unknown
        cash_at_source[source_at] = cumulative_cash if cumulative_unknown == 0 else None
    reconstructed_cash = Decimal(0)
    cash_known = True
    for row in pnl_rows:
        row.update(daily.get(row["day"], {}))
        row["activity_end_at"] = min(request["cutoff"], row["end_at"])
        row["window_metrics"] = window_metrics([w for w in daily_window_groups[row["day"]] if w["end"] <= pnl_end])
        row["activity_minus_series_income"] = (row.get("income", Decimal(0)) - row["wallet_income_change"]
                                                 if row["wallet_income_change"] is not None else None)
        reconstructed_cash += sum((row.get(field, Decimal(0)) for field in
                                   ("trading_cash", "external_funding", "income")), Decimal(0))
        cash_known = cash_known and row.get("unknown_cash_events", 0) == 0
        cash_point = cash_points.get(row["source_block"])
        row["verified_pusd_cash"] = amount(cash_point["pusd_cash"]) if cash_point else None
        row["verified_cash_block_at"] = cash_point["block_at"] if cash_point else None
        row["pnl_source_lag_s"] = row["end_at"] - cash_point["block_at"] if cash_point else None
        row["activity_cash_reconstruction"] = reconstructed_cash if cash_known else None
        source_cash = cash_at_source[cash_point["block_at"]] if cash_point else None
        row["activity_cash_at_source_block_time"] = source_cash
        row["activity_minus_chain_cash"] = (source_cash - row["verified_pusd_cash"]
                                             if source_cash is not None and cash_point else None)
    activity_income = sum((row["income"] for row in daily.values()), Decimal(0))
    series_income = data["points"][-1].get("wallet_income")
    income_gap = activity_income - amount(series_income) if series_income is not None else None
    csv_path = directory / "daily.csv"
    fields = [key for key in pnl_rows[0] if key != "window_metrics"] if pnl_rows else []
    with csv_path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(clean(row) for row in pnl_rows)
    return clean({"wallet": WALLET, "cutoff": request["cutoff"], "coverage": coverage,
                  "first_available_activity": first_event, "first_available_trade": first_trade,
                  "activity_types": dict(types), "reported_cash_magnitudes_by_type": cash_by_type,
                  "funding_rows": funding, "markets_by_trade_rows": dict(slugs),
                  "distinct_market_conditions": len({key[3] for key in activity_trade_keys}),
                  "distinct_outcome_tokens": len({key[2] for key in activity_trade_keys}),
                  "indistinguishable_extra_trade_rows_preserved": sum(count - 1 for count in identical_rows.values()),
                  "trade_crosscheck": trade_crosscheck, "roles": roles,
                  "fill_shares": stats(sizes), "fill_reported_cash": stats(fill_cash),
                  "closed_btc_5m_windows": window_metrics(windows),
                  "monthly_window_metrics": {month: window_metrics(rows) for month, rows in sorted(month_groups.items())},
                  "daily": pnl_rows, "risk": risk, "official_pnl_latest": data["points"][-1],
                  "income_reconciliation": {"through_at": pnl_end, "activity_income": activity_income,
                                             "series_income": series_income, "difference": income_gap,
                                             "matched": income_gap is not None and abs(income_gap) <= Decimal("0.000001"),
                                             "limitation": "Do not call provider economic P&L independently reconciled when credited income disagrees"},
                  "activity_after_last_pnl_point": after_pnl,
                  "pnl_received_at": pnl["received_at"], "pnl_sha256": digest((directory / "pnl-daily.json").read_bytes()),
                  "archived_cash_complete": balances["complete"] if balances else False,
                  "archived_cash_sha256": digest(balances_path.read_bytes()) if balances else None,
                  "cash_balance": None, "whole_bankroll": None,
                  "cash_limitations": "Signed API activity cash flows are not a venue cash balance or marked profit; unknown actions and other wallets remain uncovered"})
