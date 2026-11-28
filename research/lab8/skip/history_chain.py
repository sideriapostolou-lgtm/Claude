"""Reproduce public Polygon receipt evidence, without account credentials.

This decodes cash-token transfers, not profit or a complete bankroll. A mint,
redemption, split, merge, bridge, trade and external deposit can all move cash;
their lifecycle evidence must be joined before any economic classification.
Raw responses and request boundaries are saved outside the source tree.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

import requests

WALLET = "0xc53375ff94e96100f2b30a4b5775db35218d69a9"
RPC = "https://polygon.drpc.org"
TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
ZERO = "0x" + "0" * 40
# Contracts, not the ambiguous symbol "USDC", distinguish these assets.
TOKENS = {
    "0x2791bca1f2de4661ed88a30c99a7a9449aa84174": ("USDC.e", 6),
    "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359": ("native USDC", 6),
    "0xc011a7e12a19f7b1f670d46f03b03f3342e82dfb": ("pUSD collateral", 6),
}


def hexword(value: Any, length: int) -> str:
    if not isinstance(value, str) or re.fullmatch(r"0x[0-9a-fA-F]{" + str(length) + "}", value) is None:
        raise ValueError("Malformed public chain identifier")
    return value.lower()


def decode_receipt(receipt: dict[str, Any], wallet: str = WALLET) -> dict[str, Any]:
    """Keep event identity and token units; do not infer economic profit."""
    wallet = hexword(wallet, 40)
    tx = hexword(receipt["transactionHash"], 64)
    block_hash = hexword(receipt["blockHash"], 64)
    if receipt.get("status") != "0x1":
        raise ValueError("Receipt is not a successful canonical execution")
    events = []
    indexes: set[int] = set()
    for log in receipt["logs"]:
        if log.get("removed") is True:
            raise ValueError("Removed log cannot be current funding evidence")
        if hexword(log["transactionHash"], 64) != tx or hexword(log["blockHash"], 64) != block_hash:
            raise ValueError("Receipt and log identities disagree")
        index = int(log["logIndex"], 16)
        if index in indexes:
            raise ValueError("Duplicate log index cannot count twice")
        indexes.add(index)
        token = hexword(log["address"], 40)
        topics = log["topics"]
        if token not in TOKENS or not topics or topics[0].lower() != TRANSFER:
            continue
        if len(topics) != 3:
            raise ValueError("Cash Transfer event has an invalid indexed layout")
        sender_word, recipient_word = hexword(topics[1], 64), hexword(topics[2], 64)
        if sender_word[2:26] != "0" * 24 or recipient_word[2:26] != "0" * 24:
            raise ValueError("Transfer address is not canonically padded")
        sender, recipient = "0x" + sender_word[-40:], "0x" + recipient_word[-40:]
        amount = int(hexword(log["data"], 64), 16)
        symbol, decimals = TOKENS[token]
        events.append({"transaction_hash": tx, "log_index": index, "contract": token,
                       "asset": symbol, "decimals": decimals, "raw_units": str(amount),
                       "amount": str(Decimal(amount).scaleb(-decimals)), "from": sender, "to": recipient,
                       "event_type": "mint" if sender == ZERO else "burn" if recipient == ZERO else "transfer",
                       "wallet_direction": "self" if sender == recipient == wallet else
                           "in" if recipient == wallet else "out" if sender == wallet else "neither"})
    return {"transaction_hash": tx, "block_hash": block_hash, "block": int(receipt["blockNumber"], 16),
            "cash_token_events": events, "wallet": wallet, "profit_usd": None,
            "complete_wallet_history": False,
            "limitation": "One receipt only. Transfers and collateral mints are not automatically deposits or profit."}


class PublicRpc:
    """Fixed public endpoint, bounded retries, and a reproducible response manifest."""

    def __init__(self, directory: Path, *, post: Callable[..., Any] = requests.post,
                 sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.time) -> None:
        self.directory, self.post, self.sleep, self.clock = directory, post, sleep, clock
        directory.mkdir(parents=True, exist_ok=True)
        self.sequence = len(list(directory.glob("response-*.json")))

    def call(self, method: str, params: list[Any]) -> Any:
        if method == "eth_call":
            # The archive audit needs only this source wallet's cash balances.
            # Keep arbitrary contract calls and transaction fields unavailable.
            if (len(params) != 2 or not isinstance(params[0], dict)
                    or set(params[0]) != {"to", "data"}
                    or params[0]["to"] not in TOKENS
                    or params[0]["data"] != "0x70a08231" + "0" * 24 + WALLET[2:]
                    or not isinstance(params[1], str)
                    or re.fullmatch(r"0x[0-9a-fA-F]+", params[1]) is None):
                raise ValueError("Only historical cash balanceOf for the public source wallet is available")
        elif method not in {"eth_chainId", "eth_getTransactionReceipt", "eth_getBlockByNumber", "eth_getCode", "eth_getLogs"}:
            raise ValueError("Only the declared public read methods are available")
        for attempt in range(3):
            self.sequence += 1
            request = {"jsonrpc": "2.0", "id": self.sequence, "method": method, "params": params}
            response = self.post(RPC, json=request, timeout=30)
            body = response.content
            name = f"response-{self.sequence:06d}.json"
            with (self.directory / name).open("xb") as stream:
                stream.write(body)
            entry = {"endpoint": RPC, "request": request, "received_at": self.clock(),
                     "status": response.status_code, "response_file": name,
                     "sha256": hashlib.sha256(body).hexdigest(),
                     "retry_after": response.headers.get("Retry-After")}
            with (self.directory / "requests.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(entry, allow_nan=False, sort_keys=True) + "\n")
            if response.status_code == 429:
                # Long/undecodable limits stop the probe; a later run can resume.
                retry = response.headers.get("Retry-After", "2")
                if not retry.isdigit() or int(retry) > 60 or attempt == 2:
                    raise ValueError("Public RPC rate limit: pause and honor the saved Retry-After")
                self.sleep(max(1, int(retry)))
                continue
            response.raise_for_status()
            decoded = json.loads(body)
            if decoded.get("id") != self.sequence or decoded.get("jsonrpc") != "2.0":
                raise ValueError("Public RPC response identity mismatch")
            if "error" in decoded or "result" not in decoded:
                raise ValueError("Public RPC returned an error; inspect the saved response")
            self.sleep(.4)
            return decoded["result"]
        raise ValueError("Public RPC retry budget exhausted")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--transaction", action="append", required=True)
    args = parser.parse_args()
    client = PublicRpc(args.output_dir)
    if client.call("eth_chainId", []) != "0x89":
        raise ValueError("Expected Polygon chain 137")
    reports = []
    for transaction in args.transaction:
        transaction = hexword(transaction, 64)
        receipt = client.call("eth_getTransactionReceipt", [transaction])
        if receipt is None:
            reports.append({"transaction_hash": transaction, "status": "unavailable", "profit_usd": None})
            continue
        report = decode_receipt(receipt)
        block = client.call("eth_getBlockByNumber", [receipt["blockNumber"], False])
        if block is None or block["hash"].lower() != report["block_hash"]:
            raise ValueError("Receipt block cannot be independently confirmed")
        report["block_timestamp"] = int(block["timestamp"], 16)
        reports.append(report)
    (args.output_dir / "receipt-summary.json").write_text(json.dumps(reports, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"receipts": len(reports), "output": str(args.output_dir), "complete_history": False}))


if __name__ == "__main__":
    main()
