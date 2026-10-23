"""Public archived pUSD cash at the source blocks of the venue's daily series.

These are historical source-wallet token balances, not portfolio equity, net
profit, another person's bankroll or the owner's trading-account cash.
"""

from __future__ import annotations

import argparse
import json
import time
from decimal import Decimal
from pathlib import Path
from typing import Any

from history import atomic_json, digest
from history_chain import WALLET, PublicRpc, hexword

PUSD = "0xc011a7e12a19f7b1f670d46f03b03f3342e82dfb"
BALANCE_DATA = "0x70a08231" + WALLET[2:].rjust(64, "0")


def collect(pnl_path: Path, directory: Path, client: Any = None) -> dict[str, Any]:
    directory.mkdir(parents=True, exist_ok=True)
    raw = pnl_path.read_bytes()
    data = json.loads(raw)["response"]["data"]
    if data["proxy_wallet"].lower() != WALLET:
        raise ValueError("Unexpected P&L wallet")
    path = directory / "balances.json"
    if path.exists():
        result = json.loads(path.read_text())
        if (result["pnl_sha256"] != digest(raw) or result["wallet"] != WALLET
                or result["contract"] != PUSD):
            raise ValueError("Archived-balance inputs changed")
    else:
        result = {"wallet": WALLET, "contract": PUSD, "decimals": 6, "pnl_sha256": digest(raw),
                  "complete": False, "points": [], "net_profit": None,
                  "scope": "Historical pUSD cash only at explicit Polygon source blocks"}
    client = client or PublicRpc(directory, sleep=lambda delay: time.sleep(max(1.0, delay)))
    if client.call("eth_chainId", []) != "0x89":
        raise ValueError("Expected Polygon chain 137")
    source_points = data["points"]
    for index, point in enumerate(source_points):
        block = point["source_block"]
        if type(block) is not int or block <= 0:
            raise ValueError("Invalid source block")
        if index < len(result["points"]):
            saved = result["points"][index]
            if saved["source_block"] != block or saved["series_at"] != point["timestamp"]:
                raise ValueError("Archived-balance checkpoint order changed")
            continue
        header = client.call("eth_getBlockByNumber", [hex(block), False])
        if not isinstance(header, dict) or int(header["number"], 16) != block:
            raise ValueError("Archived block header is unavailable or different")
        block_hash = hexword(header["hash"], 64)
        units = client.call("eth_call", [{"to": PUSD, "data": BALANCE_DATA}, hex(block)])
        integer = int(hexword(units, 64), 16)
        result["points"].append({"series_at": point["timestamp"], "source_block": block,
                                 "block_hash": block_hash, "block_at": int(header["timestamp"], 16),
                                 "raw_units": str(integer), "pusd_cash": str(Decimal(integer).scaleb(-6))})
        result["complete"] = len(result["points"]) == len(source_points)
        atomic_json(path, result)
        if len(result["points"]) % 10 == 0 or result["complete"]:
            print(json.dumps({"cash_points": len(result["points"]), "complete": result["complete"]}), flush=True)
    if len(result["points"]) != len(source_points):
        raise ValueError("Archived-balance checkpoint length changed")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pnl", type=Path, required=True)
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    collect(args.pnl, args.directory)


if __name__ == "__main__":
    main()
