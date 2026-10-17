"""Public evidence decoding cannot turn funding or duplicate events into profit."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "skipwatch_history_chain", Path(__file__).parents[1] / "research/lab8/skip/history_chain.py")
assert SPEC and SPEC.loader
chain = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(chain)


def receipt(*, token=None, sender=None, recipient=None, amount=4_000_000_000):
    tx, block = "0x" + "1" * 64, "0x" + "2" * 64
    log = {"transactionHash": tx, "blockHash": block, "logIndex": "0x5", "removed": False,
           "address": token or "0xc011a7e12a19f7b1f670d46f03b03f3342e82dfb",
           "topics": [chain.TRANSFER, "0x" + "0" * 24 + (sender or chain.ZERO)[2:],
                      "0x" + "0" * 24 + (recipient or chain.WALLET)[2:]],
           "data": f"0x{amount:064x}"}
    return {"transactionHash": tx, "blockHash": block, "blockNumber": "0x14", "status": "0x1", "logs": [log]}


def test_collateral_mint_retains_units_and_is_never_labeled_profit():
    report = chain.decode_receipt(receipt())
    row = report["cash_token_events"][0]
    assert row["asset"] == "pUSD collateral" and row["event_type"] == "mint"
    assert row["amount"] == "4000.000000" and row["wallet_direction"] == "in"
    assert report["profit_usd"] is None and report["complete_wallet_history"] is False


def test_usdc_contracts_remain_distinct_even_with_the_same_symbol():
    bridged = chain.decode_receipt(receipt(token="0x2791bca1f2de4661ed88a30c99a7a9449aa84174"))
    native = chain.decode_receipt(receipt(token="0x3c499c542cef5e3811e1192ce70d8cc03d5c3359"))
    assert bridged["cash_token_events"][0]["asset"] == "USDC.e"
    assert native["cash_token_events"][0]["asset"] == "native USDC"


@pytest.mark.parametrize("mutation", ["duplicate", "different_tx", "removed", "bad_padding", "reverted"])
def test_invalid_or_duplicate_receipt_evidence_is_rejected(mutation):
    value = receipt()
    if mutation == "duplicate":
        value["logs"] *= 2
    elif mutation == "different_tx":
        value["logs"][0]["transactionHash"] = "0x" + "3" * 64
    elif mutation == "removed":
        value["logs"][0]["removed"] = True
    elif mutation == "bad_padding":
        value["logs"][0]["topics"][1] = "0x" + "f" * 64
    else:
        value["status"] = "0x0"
    with pytest.raises(ValueError):
        chain.decode_receipt(value)


def test_self_transfers_do_not_become_external_funding():
    report = chain.decode_receipt(receipt(sender=chain.WALLET, recipient=chain.WALLET))
    assert report["cash_token_events"][0]["wallet_direction"] == "self"
    assert report["profit_usd"] is None


def test_rate_limit_backoff_and_failed_response_are_preserved(tmp_path):
    calls, sleeps = [], []

    class Response:
        def __init__(self, status, body, headers=None):
            self.status_code, self.content, self.headers = status, json.dumps(body).encode(), headers or {}

        def raise_for_status(self):
            assert self.status_code == 200

    def post(url, **kwargs):
        calls.append(kwargs["json"])
        if len(calls) == 1:
            return Response(429, {"error": "limited"}, {"Retry-After": "3"})
        return Response(200, {"jsonrpc": "2.0", "id": kwargs["json"]["id"], "result": "0x89"})

    client = chain.PublicRpc(tmp_path, post=post, sleep=sleeps.append, clock=lambda: 1000)
    assert client.call("eth_chainId", []) == "0x89"
    assert sleeps == [3, .4] and len(list(tmp_path.glob("response-*.json"))) == 2
    assert len((tmp_path / "requests.jsonl").read_text().splitlines()) == 2
    with pytest.raises(ValueError, match="public read"):
        client.call("eth_sendRawTransaction", ["never sent"])
    assert len(calls) == 2


def test_historical_cash_balance_reads_cannot_become_arbitrary_contract_calls(tmp_path):
    calls = []

    class Response:
        status_code = 200

        def __init__(self, sequence):
            self.headers = {}
            self.content = json.dumps({"jsonrpc": "2.0", "id": sequence, "result": "0x123"}).encode()

        def raise_for_status(self):
            pass

    def post(url, **kwargs):
        calls.append(kwargs["json"])
        return Response(kwargs["json"]["id"])

    client = chain.PublicRpc(tmp_path, post=post, sleep=lambda _: None)
    tx = {"to": "0xc011a7e12a19f7b1f670d46f03b03f3342e82dfb",
          "data": "0x70a08231" + "0" * 24 + chain.WALLET[2:]}
    assert client.call("eth_call", [tx, "0x123"]) == "0x123"
    for params in ([tx, "latest"], [{**tx, "from": chain.WALLET}, "0x123"],
                   [{**tx, "data": "0xdeadbeef"}, "0x123"],
                   [{**tx, "to": chain.WALLET}, "0x123"], [tx]):
        with pytest.raises(ValueError, match="historical cash balanceOf"):
            client.call("eth_call", params)
    assert len(calls) == 1
