"""Public market rules, completed hourly candles and archived wallet cash evidence."""
from __future__ import annotations

import argparse
import calendar
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from lucas_history import CHAIN, HISTORY, WALLET, get_json


def collect_markets(directory: Path) -> None:
    slugs = sorted({r["event_slug"] for r in HISTORY.iter_rows(directory / "activity") if r["type"] == "TRADE"})
    for index, slug in enumerate(slugs):
        get_json("https://gamma-api.polymarket.com/events", {"slug": slug}, directory / "markets" / (slug + ".json"))
        if index % 10 == 0:
            print(json.dumps({"market_events_collected": index + 1, "total": len(slugs)}), flush=True)


def collect_candles(directory: Path) -> None:
    fills = [r for r in HISTORY.iter_rows(directory / "activity") if r["type"] == "TRADE"]
    start = min(r["timestamp"] for r in fills) // 3600 * 3600 - 31 * 86400
    end = max(r["timestamp"] for r in fills) // 3600 * 3600 + 3600
    for coin in ("BTC", "ETH"):
        for at in range(start, end, 299 * 3600):
            get_json(f"https://api.exchange.coinbase.com/products/{coin}-USD/candles",
                     {"granularity": 3600, "start": datetime.fromtimestamp(at, UTC).isoformat(),
                      "end": datetime.fromtimestamp(min(at + 299 * 3600, end), UTC).isoformat()},
                     directory / "candles" / coin / f"{at}.json")
        print(json.dumps({"hourly_candles_collected": coin}), flush=True)


def month_boundary(at: int) -> int:
    dt = datetime.fromtimestamp(at, UTC)
    last = calendar.monthrange(dt.year, dt.month)[1]
    return int(datetime(dt.year, dt.month, last, 23, 59, 59, tzinfo=UTC).timestamp()) + 1


def collect_cash(directory: Path) -> None:
    """Read each month's provider source block, all three distinct cash contracts."""
    path = directory / "cash.json"
    result: dict[str, Any] = json.loads(path.read_text()) if path.exists() else {"wallet": WALLET, "points": [], "funding_receipts": []}
    rpc = CHAIN.PublicRpc(directory / "chain")
    if rpc.call("eth_chainId", []) != "0x89":
        raise ValueError("Wrong chain")
    pnl = json.loads((directory / "pnl-daily.json").read_text())["response"]["data"]["points"]
    chosen: dict[str, dict[str, Any]] = {}
    for point in pnl:
        # At midnight on day 1 this is the preceding month's closing sample.
        month = datetime.fromtimestamp(point["timestamp"] - 1, UTC).strftime("%Y-%m")
        chosen[month] = point
    for month, point in chosen.items():
        if any(x["month"] == month for x in result["points"]):
            continue
        block = rpc.call("eth_getBlockByNumber", [hex(point["source_block"]), False])
        balances = {}
        for contract, (symbol, decimals) in CHAIN.TOKENS.items():
            data = "0x70a08231" + "0" * 24 + WALLET[2:]
            raw = rpc.call("eth_call", [{"to": contract, "data": data}, hex(point["source_block"])])
            # A contract did not yet exist: eth_call returns empty data, not a balance.
            balances[symbol] = None if raw == "0x" else str(Decimal(int(raw, 16)).scaleb(-decimals))
        result["points"].append({"month": month, "series_at": point["timestamp"], "source_block": point["source_block"],
                                 "block_at": int(block["timestamp"], 16), "block_hash": block["hash"], "balances": balances})
        HISTORY.atomic_json(path, result)
        print(json.dumps({"cash_months": len(result["points"])}), flush=True)
    funding = [r for r in HISTORY.iter_rows(directory / "activity") if r["type"] in {"DEPOSIT", "WITHDRAWAL"}]
    for row in funding:
        if any(x["transaction_hash"] == row["transaction_hash"] for x in result["funding_receipts"]):
            continue
        receipt = rpc.call("eth_getTransactionReceipt", [row["transaction_hash"]])
        if receipt is None:
            result["funding_receipts"].append({"transaction_hash": row["transaction_hash"], "unavailable": True})
        else:
            decoded = CHAIN.decode_receipt(receipt, WALLET)
            result["funding_receipts"].append(decoded)
        HISTORY.atomic_json(path, result)
    result["complete"] = True
    HISTORY.atomic_json(path, result)
    print(json.dumps({"cash_months": len(result["points"]), "funding_receipts": len(result["funding_receipts"])}), flush=True)


def collect_early_cash(directory: Path) -> None:
    """Before trading/P&L began, inspect actual last blocks before month boundaries."""
    path = directory / "cash.json"
    result = json.loads(path.read_text())
    rpc = CHAIN.PublicRpc(directory / "chain")
    cache: dict[int, dict[str, Any]] = {}

    def header(number: int) -> dict[str, Any]:
        if number not in cache:
            value = rpc.call("eth_getBlockByNumber", [hex(number), False])
            if not isinstance(value, dict) or int(value["number"], 16) != number:
                raise ValueError("Unexpected archived block")
            cache[number] = value
        return cache[number]

    def balances(number: int) -> dict[str, str | None]:
        out = {}
        for contract, (symbol, decimals) in CHAIN.TOKENS.items():
            data = "0x70a08231" + "0" * 24 + WALLET[2:]
            raw = rpc.call("eth_call", [{"to": contract, "data": data}, hex(number)])
            out[symbol] = None if raw == "0x" else str(Decimal(int(raw, 16)).scaleb(-decimals))
        return out

    rows = list(HISTORY.iter_rows(directory / "activity"))
    first = next(row for row in rows if row["type"] == "DEPOSIT")
    receipt = next(row for row in result["funding_receipts"] if row["transaction_hash"] == first["transaction_hash"])
    first_block = receipt["block"]
    first_chart = min((row for row in result["points"] if "source" not in row), key=lambda row: row["month"])
    first_chart_month = first_chart["month"]
    target = month_boundary(first["timestamp"])
    while datetime.fromtimestamp(target - 1, UTC).strftime("%Y-%m") < first_chart_month:
        key = datetime.fromtimestamp(target - 1, UTC).strftime("%Y-%m")
        if not any(row["month"] == key for row in result["points"]):
            low, high = first_block, first_chart["source_block"]
            if int(header(low)["timestamp"], 16) >= target or int(header(high)["timestamp"], 16) < target:
                raise ValueError("Monthly block search bounds do not bracket boundary")
            while high - low > 1:
                middle = (low + high) // 2
                if int(header(middle)["timestamp"], 16) < target:
                    low = middle
                else:
                    high = middle
            block = header(low)
            result["points"].append({"month": key, "series_at": target, "source_block": low,
                                     "block_at": int(block["timestamp"], 16), "block_hash": block["hash"],
                                     "balances": balances(low), "source": "Last Polygon block before month boundary, binary searched"})
            result["points"].sort(key=lambda row: row["month"])
            HISTORY.atomic_json(path, result)
        target = month_boundary(target)
    if "initial_cash" not in result:
        result["initial_cash"] = {"before_first_indexed_deposit": {"block": first_block - 1, "balances": balances(first_block - 1)},
                                  "after_first_indexed_deposit": {"block": first_block, "balances": balances(first_block)}}
        HISTORY.atomic_json(path, result)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["markets", "candles", "cash", "early-cash"])
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    {"markets": collect_markets, "candles": collect_candles, "cash": collect_cash, "early-cash": collect_early_cash}[args.command](args.directory)


if __name__ == "__main__":
    main()
