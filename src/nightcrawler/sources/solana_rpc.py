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

from typing import Any

from nightcrawler.http import HttpClient

__all__ = ["DEFAULT_RPC_URL", "RpcError", "SolanaRpc"]

DEFAULT_RPC_URL = "https://api.mainnet-beta.solana.com"


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
        self._next_id = 1

    def call(self, method: str, params: list[Any] | None = None) -> Any:
        """POST ``{"jsonrpc": "2.0", "id": n, "method": method, "params": params}``; return ``result``.

        Raises :class:`RpcError` when the body has ``error``; ``HttpError`` on transport failure.
        """
        raise NotImplementedError

    def mint_info(self, mint: str) -> dict[str, Any] | None:
        """Parsed mint account, or ``None`` if the account does not exist.

        Returns ``{"mint": str, "mint_authority": str|None, "freeze_authority": str|None,
        "decimals": int, "supply": int (base units), "program": "spl-token"|"spl-token-2022",
        "extensions": [names], "extension_states": {name: state_dict}}``.
        Raises ``RpcError`` if the account is not a mint.
        """
        raise NotImplementedError

    def get_balance(self, pubkey: str) -> int:
        """Lamports held by ``pubkey`` (``getBalance`` ``value``)."""
        raise NotImplementedError

    def simulate(self, tx_b64: str) -> dict[str, Any]:
        """``simulateTransaction`` with ``{"encoding": "base64", "sigVerify": true,
        "replaceRecentBlockhash": false, "commitment": "processed"}``.

        Returns ``{"err": Any|None, "logs": [str], "units_consumed": int|None}``.
        ``err`` not None means the swap would fail - the live broker aborts.
        """
        raise NotImplementedError

    def signature_status(self, signature: str) -> dict[str, Any] | None:
        """``getSignatureStatuses([sig], {"searchTransactionHistory": true})`` first value.

        Returns ``{"slot": int, "confirmations": int|None, "err": Any|None,
        "confirmation_status": "processed"|"confirmed"|"finalized"|None}`` or
        ``None`` if unknown.
        """
        raise NotImplementedError
