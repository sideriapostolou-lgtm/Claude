"""Reproduce the frozen public-wallet accounting, offline and without credentials.

Run from any directory: ``python /path/to/research/wallet_playbooks/audit_skip.py``.
This audits recorded fills and redemptions, not executable strategy profitability.
Later rebates are unallocated; the matched/directional split uses average cost.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import statistics
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

WALLET = "0xc53375ff94e96100f2b30a4b5775db35218d69a9"
IDENTITY = (
    "timestamp", "side", "token_id", "condition_id", "size", "price", "transaction_hash",
)
ZERO = Decimal(0)
Row = dict[str, Any]


def require(condition: bool, message: str) -> None:
    """Fail even when Python runs with assertions disabled."""
    if not condition:
        raise ValueError(message)


def decimal(value: Any) -> Decimal:
    result = Decimal(str(value))
    require(result.is_finite(), "Non-finite public amount")
    return result


def load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def identity(row: Row) -> tuple[Any, ...]:
    # Preserve multiplicity: economically identical fills need not be duplicates.
    return tuple(row[field] for field in IDENTITY)


def load_stream(directory: Path, protocol: Row) -> list[Row]:
    """Verify raw hashes, fixed query, cursor continuity and provider completion."""
    manifest = load_json(directory / "manifest.json")
    params = manifest["params"]
    require(params["user"] == WALLET, "Unexpected query wallet")
    for field in ("start", "end"):
        require(params[field] == protocol[field], "Query differs from frozen period")
    endpoint = "activity" if directory.name == "activity" else "trades"
    require(manifest["endpoint"] == endpoint, "Unexpected API endpoint")
    if endpoint == "trades":
        expected_role = "true" if directory.name == "taker_trades" else "false"
        require(params["taker_only"] == expected_role, "Wrong taker cohort")
    rows: list[Row] = []
    cursor: str | None = None
    seen: set[str] = set()
    require(bool(manifest["pages"]), "Empty page manifest")
    for index, page in enumerate(manifest["pages"]):
        require(index == 0 or cursor is not None, "Page follows a completed cursor")
        filename = page["file"]
        require(Path(filename).name == filename, "Non-local evidence filename")
        with gzip.open(directory / filename, "rb") as stream:
            raw = stream.read()
        require(hashlib.sha256(raw).hexdigest() == page["sha256"], "Page hash mismatch")
        envelope = json.loads(raw)
        url = urlsplit(envelope["url"])
        expected = {key: [str(value)] for key, value in params.items()}
        if cursor:
            expected["cursor"] = [cursor]
        require(
            url.scheme == "https" and url.netloc == "data-api.polymarket.com"
            and url.path == f"/v2/{endpoint}" and parse_qs(url.query) == expected,
            "Frozen query or cursor chain changed",
        )
        payload = envelope["response"]
        batch, pagination = payload["data"], payload["pagination"]
        require(pagination["offset"] == len(rows), "Page offset mismatch")
        require(pagination["limit"] == params["limit"], "Page limit mismatch")
        require(len(batch) == page["rows"], "Page row count mismatch")
        cursor = pagination["next_cursor"]
        require(cursor == page["next_cursor"], "Cursor differs from manifest")
        require(pagination["has_more"] == bool(cursor), "Inconsistent continuation")
        require(not cursor or cursor not in seen, "Repeated cursor")
        if cursor:
            seen.add(cursor)
        rows.extend(batch)
    require(manifest["complete"] is True and cursor is None, "Incomplete public index walk")
    require(manifest["next_cursor"] is None, "Manifest contains unfinished cursor")
    require(len(rows) == manifest["rows"], "Total row count mismatch")
    for row in rows:
        require(row["proxy_wallet"].lower() == WALLET, "Unexpected response wallet")
        require(protocol["start"] <= row["timestamp"] <= protocol["end"],
                "Row outside frozen query interval")
    return rows


def accounting(
    trades: list[Row], activity: list[Row], takers: list[Row], markets: list[Row],
    start: int, end: int,
) -> Row:
    """Reconcile source cash without adding recorded fees a second time."""
    for row in trades + activity + takers:
        require(row["proxy_wallet"].lower() == WALLET, "Unexpected ledger wallet")
    all_ids = Counter(identity(row) for row in trades)
    trade_activity = [row for row in activity if row["type"] == "TRADE"]
    require(all_ids == Counter(identity(row) for row in trade_activity),
            "Activity and fill economic multisets disagree")
    taker_ids = Counter(identity(row) for row in takers)
    require(not taker_ids - all_ids, "Taker cohort contains unknown fills")
    require(all(row["side"] == "BUY" for row in trade_activity),
            "SELL or unknown action invalidates buy-only accounting")
    windows: dict[str, Row] = {}
    conditions: dict[str, set[str]] = defaultdict(set)
    roles: dict[str, dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    for row in trade_activity:
        slug = row["slug"]
        require(slug.startswith("btc-updown-5m-"), "Unexpected market family")
        opening = int(slug.rsplit("-", 1)[1])
        # One complete market window is excluded at each request boundary.
        if opening < start + 300 or opening + 300 > end + 1 - 300:
            continue
        conditions[slug].add(row["condition_id"])
        quantity, price, cash = (decimal(row[field]) for field in ("size", "price", "usdc_size"))
        require(quantity > 0 and ZERO <= price <= 1 and cash >= 0, "Invalid trade economics")
        side = row["outcome"].lower()
        require(side in ("up", "down"), "Unexpected outcome")
        key = identity(row)
        role = "taker" if taker_ids[key] else "maker"
        if role == "taker":
            taker_ids[key] -= 1
        gross, increment = quantity * price, cash - quantity * price
        for field, value in (("q", quantity), ("cash", cash), ("gross", gross),
                             ("cost_increment", increment), ("fills", Decimal(1))):
            roles[role][field] += value
        window = windows.setdefault(slug, {"slug": slug, "fills": 0, **{
            field: ZERO for field in ("up_q", "down_q", "up_cash", "down_cash",
                                      "up_gross", "down_gross", "fee")
        }})
        window[side + "_q"] += quantity
        window[side + "_cash"] += cash
        window[side + "_gross"] += gross
        window["fee"] += increment
        window["fills"] += 1

    market_by_slug: dict[str, Row] = {}
    for market in markets:
        require(market["slug"] not in market_by_slug, "Duplicate market metadata")
        market_by_slug[market["slug"]] = market
    for slug, window in windows.items():
        market = market_by_slug[slug]
        require(conditions[slug] == {market["conditionId"]},
                "Fill condition IDs disagree with resolved market")
        require(market["closed"] is True and market["umaResolutionStatus"] == "resolved",
                "Market is not finally resolved")
        outcomes = json.loads(market["outcomes"])
        prices = [decimal(value) for value in json.loads(market["outcomePrices"])]
        require(len(outcomes) == 2 and len(prices) == 2 and set(prices) == {ZERO, Decimal(1)},
                "Market does not have a unique binary winner")
        winner = outcomes[prices.index(Decimal(1))].lower()
        require({outcome.lower() for outcome in outcomes} == {"up", "down"},
                "Settlement outcomes differ from held outcomes")
        require(window["up_q"] > 0 and window["down_q"] > 0, "Missing side in pair accounting")
        selected = [row for row in activity if row.get("slug") == slug]
        require(all(row["type"] in ("TRADE", "REDEEM") for row in selected),
                "Unaccounted activity type in selected market")
        redemptions = [row for row in selected if row["type"] == "REDEEM"]
        require(bool(redemptions), "Missing redemption evidence")
        redeemed = sum((decimal(row["usdc_size"]) for row in redemptions), ZERO)
        payout = window[winner + "_q"]
        require(redeemed == payout, "Redemption differs from resolved winning holdings")
        window["payout"] = payout
        window["recorded_redemptions"] = redeemed
        window["pnl_before_fee"] = payout - window["up_gross"] - window["down_gross"]
        window["pnl_after_purchase_cash"] = payout - window["up_cash"] - window["down_cash"]
        pair_cost = window["up_cash"] / window["up_q"] + window["down_cash"] / window["down_q"]
        window["pair_cost_cash"] = pair_cost
        window["locked_after_purchase_cash"] = min(window["up_q"], window["down_q"]) * (1 - pair_cost)
        window["directional_after_purchase_cash"] = (
            window["pnl_after_purchase_cash"] - window["locked_after_purchase_cash"]
        )
        window["larger_side_won"] = (
            window["up_q"] != window["down_q"]
            and (window["up_q"] > window["down_q"]) == (winner == "up")
        )
    require(bool(windows), "No complete interior windows")
    fields = (
        "up_q", "down_q", "up_gross", "down_gross", "up_cash", "down_cash", "fee", "payout",
        "pnl_before_fee", "pnl_after_purchase_cash", "locked_after_purchase_cash",
        "directional_after_purchase_cash", "recorded_redemptions",
    )
    return {
        "windows": len(windows),
        "totals": {field: sum((window[field] for window in windows.values()), ZERO) for field in fields},
        "roles": dict(roles),
        "redemption_matches_payout_windows": len(windows),
        "pair_cash_below_1_windows": sum(window["pair_cost_cash"] < 1 for window in windows.values()),
        "pair_cash_median": statistics.median(window["pair_cost_cash"] for window in windows.values()),
        "profitable_windows": sum(window["pnl_after_purchase_cash"] > 0 for window in windows.values()),
        "larger_side_won_windows": sum(window["larger_side_won"] for window in windows.values()),
        "worst_window_pnl": min(window["pnl_after_purchase_cash"] for window in windows.values()),
        "best_window_pnl": max(window["pnl_after_purchase_cash"] for window in windows.values()),
    }


def equal_amount(actual: Any, expected: Any, name: str) -> None:
    # Derived average-cost attribution can differ at the last Decimal precision digit.
    require(abs(decimal(actual) - decimal(expected)) <= Decimal("1e-18"),
            f"Frozen accounting mismatch: {name}")


def compare_frozen(result: Row, directory: Path) -> None:
    frozen = load_json(directory / "accounting-summary.json")
    for group in ("totals", "roles"):
        actual, expected = result[group], frozen[group]
        if group == "totals":
            for field, value in expected.items():
                equal_amount(actual[field], value, field)
        else:
            for role, values in expected.items():
                for field, value in values.items():
                    equal_amount(actual[role][field], value, f"{role}.{field}")
    for field in ("windows", "redemption_matches_payout_windows", "pair_cash_below_1_windows",
                  "pair_cash_median", "profitable_windows", "larger_side_won_windows"):
        equal_amount(result[field], frozen[field], field)
    for label in ("best", "worst"):
        equal_amount(result[f"{label}_window_pnl"],
                     frozen[f"{label}_window"]["pnl_after_purchase_cash"], label)
    independent = load_json(directory / "independent-accounting.json")
    totals = result["totals"]
    amounts = {
        "purchase": totals["up_cash"] + totals["down_cash"],
        "redemptions": totals["recorded_redemptions"],
        "payout_from_gamma_and_quantity": totals["payout"],
        "gross_price_times_size": totals["up_gross"] + totals["down_gross"],
        "increment_in_actual_purchase_cash": totals["fee"],
        "net_before_later_rebates": totals["pnl_after_purchase_cash"],
        "windows": result["windows"],
    }
    for field, value in amounts.items():
        equal_amount(value, independent[field], field)
    require(independent["each_redemption_matches_quantity_gamma"] is True,
            "Independent redemption check did not pass")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path,
                        default=Path(__file__).resolve().parent / "evidence" / "skip")
    directory = parser.parse_args().evidence
    protocol = load_json(directory / "protocol.json")
    streams = {name: load_stream(directory / name, protocol)
               for name in ("trades", "activity", "taker_trades")}
    markets = [market for path in sorted(directory.glob("gamma-*.json"))
               for market in load_json(path)["response"]]
    result = accounting(streams["trades"], streams["activity"], streams["taker_trades"],
                        markets, protocol["start"], protocol["end"])
    compare_frozen(result, directory)
    result["frozen_comparisons_passed"] = True
    result["scope"] = "Observed wallet fills; after purchase costs, before unallocated later rebates"
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
