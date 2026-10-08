"""Solana JSON-RPC client: envelope/errors, Token-2022 mint parsing, balance, simulate, status."""

from __future__ import annotations

import os

import pytest

from fakes import FakeRequest
from nightcrawler.http import HttpClient, HttpError
from nightcrawler.models import SOL_MINT, TOKEN_2022_PROGRAM_ID, TOKEN_PROGRAM_ID
from nightcrawler.sources.solana_rpc import (
    DEFAULT_RPC_URL,
    JUPITER_PROGRAM_ID,
    PUMPSWAP_PROGRAM_ID,
    SWAP_FEE_ACCOUNT_KEYS,
    RpcError,
    SolanaRpc,
    is_helius_url,
)

GARY = "8ZCmwpW3MtC5UpNcZf7U4HMvRNTo71syU11BDiAFpump"
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
RPC_URL = "https://rpc.example.com/?api-key=SECRET"


@pytest.fixture
def rpc(http_client: HttpClient) -> SolanaRpc:
    return SolanaRpc(http_client, url=RPC_URL)


def _result(value) -> dict:
    return {"jsonrpc": "2.0", "id": 1, "result": {"context": {"slot": 1}, "value": value}}


def _mint_account(info: dict, program: str | None = "spl-token-2022", owner: str = TOKEN_2022_PROGRAM_ID) -> dict:
    data = {"parsed": {"type": "mint", "info": info}}
    if program:
        data["program"] = program
    return {"data": data, "owner": owner, "lamports": 1, "executable": False}


# --------------------------------------------------------------------------- call


def test_call_posts_a_jsonrpc_envelope_with_increasing_ids(rpc, fake_http):
    fake_http.register(RPC_URL, lambda req: {"jsonrpc": "2.0", "id": req.json["id"], "result": req.json["id"] * 10},
                       method="POST")

    assert rpc.call("getSlot") == 10
    assert rpc.call("getBalance", ["X"]) == 20

    first, second = fake_http.calls
    assert first.method == "POST" and first.url == RPC_URL
    assert first.json == {"jsonrpc": "2.0", "id": 1, "method": "getSlot", "params": []}
    assert second.json["id"] == 2 and second.json["params"] == ["X"]


def test_call_raises_rpc_error_for_error_bodies(rpc, fake_http):
    fake_http.register_fixture(RPC_URL, "rpc_getTokenLargestAccounts_429")  # disabled on the public RPC

    with pytest.raises(RpcError) as info:
        rpc.call("getTokenLargestAccounts", [GARY])

    assert info.value.code == 429 and info.value.method == "getTokenLargestAccounts"
    assert "Too many requests" in info.value.message


@pytest.mark.parametrize("body", [[], "\"a JSON string\"", {"error": "plain string"}])
def test_call_rejects_non_jsonrpc_bodies(rpc, fake_http, body):
    fake_http.register(RPC_URL, body)

    with pytest.raises(RpcError):
        rpc.call("getSlot")


def test_transport_errors_raise_http_error_with_redacted_url(rpc, fake_http):
    fake_http.register(RPC_URL, {"error": "down"}, status=503)

    with pytest.raises(HttpError) as info:
        rpc.call("getSlot")
    assert "SECRET" not in info.value.url and "SECRET" not in str(info.value)
    assert len(fake_http.calls) == 5  # reads are retried


# --------------------------------------------------------------------------- mint_info


def test_mint_info_parses_token_2022_fixture(rpc, fake_http):
    fake_http.register_fixture(RPC_URL, "rpc_getAccountInfo_mint")

    info = rpc.mint_info(GARY)

    assert fake_http.calls[0].json["method"] == "getAccountInfo"
    assert fake_http.calls[0].json["params"] == [GARY, {"encoding": "jsonParsed", "commitment": "confirmed"}]
    assert info["mint"] == GARY and info["program"] == "spl-token-2022"
    assert info["mint_authority"] is None and info["freeze_authority"] is None
    assert info["decimals"] == 6 and info["supply"] == 994_092_192_206_734
    assert info["extensions"] == ["metadataPointer", "tokenMetadata"]
    assert info["extension_states"]["tokenMetadata"]["symbol"] == "Gary"
    assert info["default_account_state"] is None


def test_mint_info_reports_dangerous_extensions_and_authorities(rpc, fake_http):
    fake_http.register(RPC_URL, _result(_mint_account({
        "mintAuthority": "MINTER", "freezeAuthority": "FREEZER", "decimals": 9, "supply": "5",
        "extensions": [
            {"extension": "transferFeeConfig", "state": {"newerTransferFee": {"transferFeeBasisPoints": 500}}},
            {"extension": "defaultAccountState", "state": {"accountState": "Frozen"}},
            {"extension": "nonTransferable"},
            {"state": {}},
            "junk",
        ],
    }, program=None)))

    info = rpc.mint_info("M")

    assert info["program"] == "spl-token-2022"  # derived from the owner program id
    assert (info["mint_authority"], info["freeze_authority"]) == ("MINTER", "FREEZER")
    assert info["extensions"] == ["transferFeeConfig", "defaultAccountState", "nonTransferable"]
    assert info["extension_states"]["nonTransferable"] == {}
    assert info["default_account_state"] == "frozen"


def test_mint_info_legacy_spl_token(rpc, fake_http):
    fake_http.register(RPC_URL, _result(_mint_account({"mintAuthority": None, "decimals": 6, "supply": "100"},
                                                      program=None, owner=TOKEN_PROGRAM_ID)))

    info = rpc.mint_info("M")

    assert info["program"] == "spl-token" and info["extensions"] == [] and info["extension_states"] == {}


def test_mint_info_missing_account_is_none(rpc, fake_http):
    fake_http.register(RPC_URL, _result(None))

    assert rpc.mint_info("NOPE") is None


@pytest.mark.parametrize("account", [
    {"data": {"parsed": {"type": "account", "info": {}}, "program": "spl-token"}},
    {"data": ["AAAA", "base64"], "owner": "11111111111111111111111111111111"},
])
def test_mint_info_rejects_non_mint_accounts(rpc, fake_http, account):
    fake_http.register(RPC_URL, _result(account))

    with pytest.raises(RpcError, match="not a parsed token mint"):
        rpc.mint_info("WALLET")


# --------------------------------------------------------------------------- balance / simulate / status


def test_get_balance(rpc, fake_http):
    fake_http.register(RPC_URL, _result(1_234_567))

    assert rpc.get_balance("W") == 1_234_567
    assert fake_http.calls[0].json["params"] == ["W", {"commitment": "confirmed"}]


def test_get_balance_without_value_raises(rpc, fake_http):
    fake_http.register(RPC_URL, {"jsonrpc": "2.0", "id": 1, "result": {}})

    with pytest.raises(RpcError):
        rpc.get_balance("W")


def test_simulate_success_and_request_config(rpc, fake_http):
    fake_http.register(RPC_URL, _result({"err": None, "logs": ["Program log: ok"], "unitsConsumed": 4242}))

    assert rpc.simulate("TX_B64") == {"err": None, "logs": ["Program log: ok"], "units_consumed": 4242}
    assert fake_http.calls[0].json["method"] == "simulateTransaction"
    assert fake_http.calls[0].json["params"] == ["TX_B64", {"encoding": "base64", "sigVerify": True,
                                                            "replaceRecentBlockhash": False,
                                                            "commitment": "processed"}]


def test_simulate_returns_the_error_of_a_failing_swap(rpc, fake_http):
    err = {"InstructionError": [2, {"Custom": 6001}]}
    fake_http.register(RPC_URL, _result({"err": err, "logs": None}))

    result = rpc.simulate("TX_B64")

    assert result == {"err": err, "logs": [], "units_consumed": None}


def test_simulate_without_value_raises_so_the_broker_fails_closed(rpc, fake_http):
    fake_http.register(RPC_URL, _result(None))

    with pytest.raises(RpcError, match="no value"):
        rpc.simulate("TX_B64")


def test_signature_status_found(rpc, fake_http):
    def respond(req: FakeRequest) -> dict:
        assert req.json["params"] == [["SIG"], {"searchTransactionHistory": True}]
        return _result([{"slot": 454_600_000, "confirmations": None, "err": None,
                         "confirmationStatus": "finalized", "status": {"Ok": None}}])

    fake_http.register(RPC_URL, respond)

    assert rpc.signature_status("SIG") == {"slot": 454_600_000, "confirmations": None, "err": None,
                                           "confirmation_status": "finalized"}


@pytest.mark.parametrize("value", [[None], [], None])
def test_signature_status_unknown_is_none(rpc, fake_http, value):
    fake_http.register(RPC_URL, _result(value))

    assert rpc.signature_status("SIG") is None


# --------------------------------------------------------------------------- Helius priority fees

HELIUS_LEVELS = {"min": 0.0, "low": 2.0, "medium": 10082.0, "high": 100000.0, "veryHigh": 1000000.0,
                 "unsafeMax": 50000000.0}


def test_priority_fee_levels_request_and_parse(rpc, fake_http):
    fake_http.register(RPC_URL, {"jsonrpc": "2.0", "id": "1", "result": {"priorityFeeLevels": HELIUS_LEVELS}},
                       method="POST")

    assert rpc.priority_fee_levels() == HELIUS_LEVELS
    (call,) = fake_http.calls
    assert call.json["method"] == "getPriorityFeeEstimate"
    assert call.json["params"] == [{"accountKeys": [PUMPSWAP_PROGRAM_ID, JUPITER_PROGRAM_ID],
                                    "options": {"includeAllPriorityFeeLevels": True}}]
    assert SWAP_FEE_ACCOUNT_KEYS == ("pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA",
                                     "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4")


def test_priority_fee_levels_drop_unusable_values(rpc, fake_http):
    levels = {"low": "12.5", "medium": None, "high": -1, "veryHigh": "nan", "unsafeMax": True, "x": "abc"}
    fake_http.register(RPC_URL, {"jsonrpc": "2.0", "id": 1, "result": {"priorityFeeLevels": levels}})

    assert rpc.priority_fee_levels() == {"low": 12.5}


@pytest.mark.parametrize("result", [None, {}, {"priorityFeeEstimate": 5.0}, {"priorityFeeLevels": [1, 2]}])
def test_priority_fee_levels_missing_raise_rpc_error(rpc, fake_http, result):
    fake_http.register(RPC_URL, {"jsonrpc": "2.0", "id": 1, "result": result})

    with pytest.raises(RpcError, match="priorityFeeLevels"):
        rpc.priority_fee_levels()


def test_priority_fee_levels_method_not_found_raises_rpc_error(rpc, fake_http):
    fake_http.register(RPC_URL, {"jsonrpc": "2.0", "id": 1, "error": {"code": -32601, "message": "Method not found"}})

    with pytest.raises(RpcError) as info:
        rpc.priority_fee_levels()
    assert info.value.code == -32601 and info.value.method == "getPriorityFeeEstimate"


@pytest.mark.parametrize("url, helius", [
    ("https://mainnet.helius-rpc.com/?api-key=abc", True),
    ("https://MAINNET.HELIUS-RPC.COM", True),
    ("https://staked.helius-rpc.com?api-key=abc", True),
    ("https://rpc.helius.xyz/?api-key=abc", True),
    ("https://api.mainnet-beta.solana.com", False),
    ("https://example.com/?u=helius-rpc.com", False),  # only the host counts
    ("https://helius-rpc.com.evil.example", False),
    ("", False),
])
def test_is_helius_url(url, helius):
    assert is_helius_url(url) is helius


# --------------------------------------------------------------------------- live


@pytest.mark.live
def test_live_solana_rpc_smoke():
    rpc = SolanaRpc(HttpClient(), url=os.environ.get("SOLANA_RPC_URL") or DEFAULT_RPC_URL)

    gary = rpc.mint_info(GARY)
    assert gary["program"] == "spl-token-2022" and gary["decimals"] == 6
    assert gary["mint_authority"] is None and gary["freeze_authority"] is None
    assert "tokenMetadata" in gary["extensions"] and gary["supply"] > 0
    usdc = rpc.mint_info(USDC)
    assert usdc["program"] == "spl-token" and usdc["extensions"] == []
    assert usdc["mint_authority"] and usdc["freeze_authority"]  # centrally issued: authorities kept
    assert rpc.get_balance(SOL_MINT) > 0
