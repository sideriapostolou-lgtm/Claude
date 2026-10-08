"""The bot wallet's SOL balance in PAPER mode, for the "ready for real money?" checklist (owner: O6).

docs/GOING_LIVE.md creates, funds and adds the bot wallet (``BOT_WALLET_SECRET``) while the bot is still in
paper mode. Paper mode only uses that wallet's address (to quote with), so nothing else ever reads its
balance: the engine calls :func:`record_balance` every :data:`CHECK_EVERY_S` (one ``getBalance`` RPC call)
and the page reads the result with :func:`saved_balance`. Live mode does not need this: every equity
snapshot records the wallet's SOL (``EquityPoint.sol_lamports``).

kv :data:`KV_BOT_WALLET` = ``{"address": str, "sol_lamports": int, "checked_at": epoch seconds}`` (the
address is public; the secret never leaves :mod:`nightcrawler.broker.wallet`).
"""

from __future__ import annotations

from typing import Any, NamedTuple

from nightcrawler.logging_setup import get_logger

__all__ = ["CHECK_EVERY_S", "KV_BOT_WALLET", "SavedBalance", "record_balance", "saved_balance"]

log = get_logger(__name__)

KV_BOT_WALLET = "bot_wallet.balance"
#: How often the engine reads the balance (about 144 RPC calls a day, only with BOT_WALLET_SECRET set).
CHECK_EVERY_S = 600.0


class SavedBalance(NamedTuple):
    address: str
    sol_lamports: int
    checked_at: float


def record_balance(ledger: Any, rpc: Any, address: str, now: float) -> None:
    """Read ``address``'s SOL and save it. Never raises: on an RPC failure the last reading stays (the
    checklist stops trusting it after an hour) and only the error's type is logged (the RPC URL holds a key)."""
    try:
        lamports = int(rpc.get_balance(address))
    except Exception as exc:
        log.warning("bot_wallet_balance_unavailable error=%s", type(exc).__name__)
        return
    ledger.set_kv(KV_BOT_WALLET, {"address": address, "sol_lamports": lamports, "checked_at": now})


def saved_balance(ledger: Any) -> SavedBalance | None:
    """The last reading, or None when there is none or it is malformed."""
    saved = ledger.get_kv(KV_BOT_WALLET)
    if not isinstance(saved, dict):
        return None
    address, lamports, checked_at = saved.get("address"), saved.get("sol_lamports"), saved.get("checked_at")
    if not isinstance(address, str) or not address:
        return None
    if isinstance(lamports, bool) or not isinstance(lamports, int):
        return None
    if isinstance(checked_at, bool) or not isinstance(checked_at, (int, float)):
        return None
    return SavedBalance(address, lamports, float(checked_at))
