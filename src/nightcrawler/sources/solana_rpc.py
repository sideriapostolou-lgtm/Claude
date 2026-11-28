"""Solana JSON-RPC client (owner: O1).

URL: ``settings.solana_rpc_url`` (default public mainnet; a free Helius key is
recommended - its ``?api-key=`` is redacted from logs). Budget 5 req/s.

Notes:
* ``getAccountInfo`` with ``{"encoding": "jsonParsed"}`` on a mint ->
  ``value.data.parsed.info.{mintAuthority, freezeAuthority, supply (str), decimals,
  extensions[]{extension, state}}``, ``value.data.program`` is ``spl-token`` or
  ``spl-token-2022``; ``value.owner`` is the token program id. New pump.fun
  mints are Token-2022.
* ``getTokenLargestAccounts`` is DISABLED (429) on the public RPC - do not use.
* JSON-RPC errors come back as HTTP 200 with ``{"error": {code, message}}``
  -> raise :class:`RpcError`. HTTP 429/5xx are retried by ``HttpClient``.
* ``getPriorityFeeEstimate`` is a Helius extension (:func:`is_helius_url`):
  ``[{"accountKeys": [...], "options": {"includeAllPriorityFeeLevels": true}}]`` ->
  ``result.priorityFeeLevels = {min, low, medium, high, veryHigh, unsafeMax}`` in
  MICRO-lamports per compute unit.
"""

from __future__ import annotations

import itertools
from collections.abc import Sequence
from typing import Any

from nightcrawler.http import HttpClient, host_of
from nightcrawler.models import TOKEN_2022_PROGRAM_ID, TOKEN_PROGRAM_ID
from nightcrawler.sources._parse import get_path, to_float, to_int

__all__ = ["DEFAULT_RPC_URL", "JUPITER_PROGRAM_ID", "PUMPSWAP_PROGRAM_ID", "SWAP_FEE_ACCOUNT_KEYS", "RpcError",
           "SolanaRpc", "is_helius_url"]

DEFAULT_RPC_URL = "https://api.mainnet-beta.solana.com"
_PROGRAM_NAMES = {TOKEN_PROGRAM_ID: "spl-token", TOKEN_2022_PROGRAM_ID: "spl-token-2022"}
#: PumpSwap AMM program (where graduated pump.fun coins trade).
PUMPSWAP_PROGRAM_ID = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"
#: Jupiter aggregator v6 program (Ultra's metis routes).
JUPITER_PROGRAM_ID = "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4"
#: Accounts whose recent priority fees price a bot swap.
SWAP_FEE_ACCOUNT_KEYS = (PUMPSWAP_PROGRAM_ID, JUPITER_PROGRAM_ID)
_HELIUS_HOST_SUFFIXES = ("helius-rpc.com", "helius.xyz")


def is_helius_url(url: str) -> bool:
    """True when ``url``'s HOST is a Helius RPC host (which serves ``getPriorityFeeEstimate``)."""
    host = host_of(url) if url else ""
    return any(host == suffix or host.endswith("." + suffix) for suffix in _HELIUS_HOST_SUFFIXES)


class RpcError(Exception):
    """JSON-RPC level error (``code`` and ``message`` from the response)."""

    def __init__(self, code: int | None, message: str, method: str = "") -> None:
        self.code = code
        self.message = message
        self.method = method
        super().__init__(f"rpc {method} error {code}: {message}")


class SolanaRpc:
    """Minimal JSON-RPC client over :class:`HttpClient` (POST, retries allowed - reads only)."""

    def __init__(self, http: HttpClient, url: str = DEFAULT_RPC_URL) -> None:
        self.http = http
        self.url = url
        self._ids = itertools.count(1)

    def call(self, method: str, params: list[Any] | None = None) -> Any:
        """POST ``{"jsonrpc": "2.0", "id": n, "method": method, "params": params}``; return ``result``.

        Raises :class:`RpcError` when the body has ``error`` (or is not a
        JSON-RPC object); ``HttpError`` on transport failure.
        """
        body = {"jsonrpc": "2.0", "id": next(self._ids), "method": method, "params": params or []}
        resp = self.http.post_json(self.url, json=body)
        if not isinstance(resp, dict):
            raise RpcError(None, "response is not a JSON-RPC object", method)
        error = resp.get("error")
        if error:
            code = to_int(error.get("code")) if isinstance(error, dict) else None
            message = error.get("message") if isinstance(error, dict) else None
            raise RpcError(code, str(message or error), method)
        return resp.get("result")

    def mint_info(self, mint: str) -> dict[str, Any] | None:
        """Parsed mint account, or ``None`` if the account does not exist.

        Returns ``{"mint": str, "mint_authority": str|None, "freeze_authority": str|None,
        "decimals": int, "supply": int (base units), "program": "spl-token"|"spl-token-2022",
        "extensions": [names], "extension_states": {name: state_dict}}`` plus
        ``"default_account_state": str|None`` (``extension_states.defaultAccountState.accountState``,
        e.g. ``"frozen"``). Raises ``RpcError`` if the account is not a mint.
        """
        method = "getAccountInfo"
        result = self.call(method, [mint, {"encoding": "jsonParsed", "commitment": "confirmed"}])
        value = get_path(result, "value")
        if value is None:
            return None
        if get_path(value, "data.parsed.type") != "mint":
            raise RpcError(None, f"account {mint} is not a parsed token mint", method)
        info = get_path(value, "data.parsed.info", {})
        states: dict[str, Any] = {
            ext["extension"]: ext.get("state") if isinstance(ext.get("state"), dict) else {}
            for ext in get_path(info, "extensions", [])
            if isinstance(ext, dict) and ext.get("extension")
        }
        return {
            "mint": mint,
            "mint_authority": info.get("mintAuthority") or None,
            "freeze_authority": info.get("freezeAuthority") or None,
            "decimals": to_int(info.get("decimals")),
            "supply": to_int(info.get("supply")),
            "program": get_path(value, "data.program") or _PROGRAM_NAMES.get(value.get("owner")),
            "extensions": list(states),
            "extension_states": states,
            "default_account_state": _lower(get_path(states, "defaultAccountState.accountState")),
        }

    def get_balance(self, pubkey: str) -> int:
        """Lamports held by ``pubkey`` (``getBalance`` ``value``). Raises ``RpcError`` if missing."""
        method = "getBalance"
        lamports = to_int(get_path(self.call(method, [pubkey, {"commitment": "confirmed"}]), "value"))
        if lamports is None:
            raise RpcError(None, "getBalance returned no value", method)
        return lamports

    def token_balance(self, owner: str, mint: str) -> int:
        """Base units of ``mint`` held ON CHAIN by ``owner``: ``getTokenAccountsByOwner(owner, {mint},
        jsonParsed, confirmed)`` summed over its accounts (Token and Token-2022; 0 without one).

        Raises :class:`RpcError` for anything unreadable (no ``value`` list, an account without a
        base-unit ``tokenAmount.amount``, an account of another mint): a balance decides whether
        tokens are written off, so it never guesses.
        """
        method = "getTokenAccountsByOwner"
        params = [owner, {"mint": mint}, {"encoding": "jsonParsed", "commitment": "confirmed"}]
        accounts = get_path(self.call(method, params), "value")
        if not isinstance(accounts, list):
            raise RpcError(None, "getTokenAccountsByOwner returned no account list", method)
        total = 0
        for account in accounts:
            info = get_path(account, "account.data.parsed.info")
            amount = to_int(get_path(info, "tokenAmount.amount")) if isinstance(info, dict) else None
            if amount is None or amount < 0 or info.get("mint") != mint:
                raise RpcError(None, "unreadable token account in getTokenAccountsByOwner", method)
            total += amount
        return total

    def simulate(self, tx_b64: str) -> dict[str, Any]:
        """``simulateTransaction`` with ``{"encoding": "base64", "sigVerify": true,
        "replaceRecentBlockhash": false, "commitment": "processed"}``.

        Returns ``{"err": Any|None, "logs": [str], "units_consumed": int|None}``.
        ``err`` not None means the swap would fail - the live broker aborts.
        Raises ``RpcError`` when the node returns no simulation value (cannot verify).
        """
        method = "simulateTransaction"
        config = {"encoding": "base64", "sigVerify": True, "replaceRecentBlockhash": False,
                  "commitment": "processed"}
        value = get_path(self.call(method, [tx_b64, config]), "value")
        if not isinstance(value, dict):
            raise RpcError(None, "simulation returned no value", method)
        logs = value.get("logs")
        return {
            "err": value.get("err"),
            "logs": [str(line) for line in logs] if isinstance(logs, list) else [],
            "units_consumed": to_int(value.get("unitsConsumed")),
        }

    def signature_status(self, signature: str) -> dict[str, Any] | None:
        """``getSignatureStatuses([sig], {"searchTransactionHistory": true})`` first value.

        Returns ``{"slot": int, "confirmations": int|None, "err": Any|None,
        "confirmation_status": "processed"|"confirmed"|"finalized"|None}`` or
        ``None`` if unknown.
        """
        result = self.call("getSignatureStatuses", [[signature], {"searchTransactionHistory": True}])
        status = get_path(result, ("value", 0))
        if not isinstance(status, dict):
            return None
        return {
            "slot": to_int(status.get("slot")),
            "confirmations": to_int(status.get("confirmations")),
            "err": status.get("err"),
            "confirmation_status": status.get("confirmationStatus") or None,
        }

    def priority_fee_levels(self, account_keys: Sequence[str] = SWAP_FEE_ACCOUNT_KEYS) -> dict[str, float]:
        """Helius ``getPriorityFeeEstimate`` for ``account_keys`` with every level included.

        Returns ``{level: micro-lamports per compute unit}`` (``min, low, medium, high,
        veryHigh, unsafeMax``); levels that are not finite non-negative numbers are left out.
        Raises :class:`RpcError` when the answer has no ``priorityFeeLevels`` object (or the
        node does not know the method - only Helius serves it).
        """
        method = "getPriorityFeeEstimate"
        params = [{"accountKeys": list(account_keys), "options": {"includeAllPriorityFeeLevels": True}}]
        levels = get_path(self.call(method, params), "priorityFeeLevels")
        if not isinstance(levels, dict):
            raise RpcError(None, "getPriorityFeeEstimate returned no priorityFeeLevels", method)
        out: dict[str, float] = {}
        for name, value in levels.items():
            number = to_float(value)  # None for bools, NaN, inf and junk
            if number is not None and number >= 0:
                out[str(name)] = number
        return out


def _lower(value: Any) -> str | None:
    return str(value).strip().lower() if value not in (None, "") else None
