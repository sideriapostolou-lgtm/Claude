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
"""

from __future__ import annotations

import itertools
from typing import Any

from nightcrawler.http import HttpClient
from nightcrawler.models import TOKEN_2022_PROGRAM_ID, TOKEN_PROGRAM_ID
from nightcrawler.sources._parse import get_path, to_int

__all__ = ["DEFAULT_RPC_URL", "RpcError", "SolanaRpc"]

DEFAULT_RPC_URL = "https://api.mainnet-beta.solana.com"
_PROGRAM_NAMES = {TOKEN_PROGRAM_ID: "spl-token", TOKEN_2022_PROGRAM_ID: "spl-token-2022"}


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
        states = {
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


def _lower(value: Any) -> str | None:
    return str(value).strip().lower() if value not in (None, "") else None
