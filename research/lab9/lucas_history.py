"""Public LucasMeow history audit; isolated reuse of the tested Lab 8 downloader.

Raw responses belong outside git. No account clients, credentials or orders.
The adapter changes only the audited PUBLIC wallet on a private module instance;
it never mutates or imports the application's live trading clients.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import time
from pathlib import Path
from types import ModuleType
from typing import Any

import requests

WALLET = "0x7f3c8979d0afa00007bae4747d5347122af05613"
SOURCE = Path(__file__).parents[1] / "lab8" / "skip"


def library(name: str) -> ModuleType:
    if name not in {"history", "history_chain"}:
        raise ValueError("Only audited public history helpers are supported")
    path = SOURCE / (name + ".py")
    spec = importlib.util.spec_from_file_location("lucas_public_" + name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Public history library missing")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.__dict__["WALLET"] = WALLET
    return module


HISTORY = library("history")
CHAIN = library("history_chain")


def get_json(url: str, params: dict[str, Any], path: Path, *, spacing: float = .4) -> Any:
    """Cache public response evidence and honor rate limits; no redirects."""
    if path.exists():
        return json.loads(path.read_text())["response"]
    allowed = ("https://user-pnl-api.polymarket.com/user-pnl", "https://gamma-api.polymarket.com/events",
               "https://api.exchange.coinbase.com/products/BTC-USD/candles",
               "https://api.exchange.coinbase.com/products/ETH-USD/candles")
    if url not in allowed:
        raise ValueError("Unexpected public research endpoint")
    path.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(6):
        started = time.time()
        response = requests.get(url, params=params, timeout=40, allow_redirects=False)
        if response.status_code == 429:
            retry = response.headers.get("Retry-After", "2")
            if not retry.isdigit() or int(retry) > 60:
                raise ValueError("Rate limited; stop and honor Retry-After")
            time.sleep(max(int(retry), 2 ** attempt))
            continue
        if response.status_code != 200:
            raise ValueError(f"Public research HTTP {response.status_code}")
        payload = response.json()
        HISTORY.atomic_json(path, {"url": response.url, "requested_at": started,
                                   "received_at": time.time(), "response": payload})
        time.sleep(spacing)
        return payload
    raise ValueError("Rate limit retry budget exhausted")


def pull(directory: Path) -> None:
    HISTORY.pull(directory)
    get_json("https://user-pnl-api.polymarket.com/user-pnl",
             {"user_address": WALLET, "interval": "all", "fidelity": "1d"},
             directory / "pnl-legacy-daily.json")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    pull(args.directory)


if __name__ == "__main__":
    main()
