"""WITHDRAW_TO: take everything back without anybody touching a key (owner: O5).

While ``WITHDRAW_TO`` (a Solana address: normally the owner's Phantom wallet) is set:

1. NO BUYS, SELL EVERYTHING. The engine treats it as ``KILL_SWITCH=sell_all`` (``Engine.handle_kill``): every
   position leaves through the usual live exit path (forced exits with the wide impact cap, write-offs,
   reconciliation of unknown swaps). Ultra leaves emptied token accounts open and nothing in this bot closes
   them (``broker/base.py``), so their deposits (about 0.002 SOL each) stay in those accounts.
2. THEN ALL THE SOL. Once nothing is open and no swap is in flight or unresolved - or :data:`SELL_WAIT_S` after the
   withdrawal began, so a coin nobody will buy cannot hold the SOL hostage - :class:`Withdrawer` sends ALL of the
   wallet's SOL to WITHDRAW_TO in ONE SystemProgram transfer signed by the keystore
   (:func:`nightcrawler.broker.keystore.sign_transfer`), simulated first, confirmed on chain, then receipted
   (kind ``withdraw``: from, to, lamports, signature, fee). Later SOL (a late sale, a new deposit) is swept
   the same way every :data:`RECHECK_S` while WITHDRAW_TO stays set.

AMOUNT (:func:`withdrawable_lamports`): ``balance - fee``, where the fee is what the network charges for that
exact message (``getFeeForMessage``: 5000 lamports per signature, no priority fee). The bot wallet pays the fee
and ends at exactly 0 lamports, which the runtime allows (the account is closed). The runtime refuses a
fee payer left with a NON-zero balance under the rent-exempt minimum (``getMinimumBalanceForRentExemption(0)``,
890,880 lamports) once the fee is taken, so ``balance - fee`` must reach that minimum; the same minimum also
lets a destination that does not exist yet be created. A smaller balance (under ~0.0009 SOL) cannot be sent
and stays.

DESTINATION (:func:`destination_problem`, :func:`account_problem`): never the bot's own address, never the System
Program or the incinerator, never an address off the ed25519 curve (a program-derived address such as a
token account), never an existing account that is a program, belongs to a program or holds data. A problem
blocks the transfer and is shown on the page; WITHDRAW_TO itself must be base58 of 32 bytes (``config``).

EXACTLY ONCE, across restarts (kv :data:`KV_STATE`):

* write-ahead: the signed transaction (no key in it; anybody may broadcast it, and it can only pay WITHDRAW_TO),
  its signature and its blockhash's ``lastValidBlockHeight`` are saved in ``pending`` together with a ``note``
  ``withdraw_sending`` receipt BEFORE the first broadcast;
* while ``pending``, only that IDENTICAL transaction is re-broadcast (one signature: it cannot execute twice)
  every :data:`REBROADCAST_S` until ``getSignatureStatuses`` is final. A NEW transfer is built only when it
  failed on chain, or when its blockhash is dead at the FINALIZED block height and the chain never saw it;
* every amount is read from the wallet right before signing, so even two transfers could never pay twice.

PAPER MODE never signs and never sends: it reads the real wallet's balance, prices the transfer with an
UNSIGNED message and shows what it would send (``note`` ``withdraw_simulated`` when that changes). Paper
positions are still sold (simulated) first.

kv ``withdraw.state`` = ``{"to", "mode", "since", "status", "error", "updated_at", "open_positions",
"pending": {...}|None, "failures", "retry_at", "next_check_at", "sent_lamports", "left_lamports",
"paper": {"balance_lamports", "fee_lamports", "would_send_lamports", "checked_at"}|None, "noted",
"last": {"to", "lamports", "signature", "fee_lamports", "at"}|None}``; ``status`` is one of :data:`STATUSES`.
"""

from __future__ import annotations

import datetime
import math
from typing import Any

from nightcrawler.base58 import is_pubkey
from nightcrawler.broker.base import BrokerError
from nightcrawler.broker.keystore import sign_transfer, transfer_message_b64
from nightcrawler.broker.live import final_swap_status
from nightcrawler.config import Settings
from nightcrawler.http import HttpError
from nightcrawler.logging_setup import get_logger
from nightcrawler.models import LAMPORTS_PER_SOL
from nightcrawler.sources.solana_rpc import RpcError

__all__ = [
    "BASE_FEE_LAMPORTS",
    "KV_STATE",
    "RENT_EXEMPT_MIN_LAMPORTS",
    "SELL_WAIT_S",
    "STAGE_S",
    "STATUSES",
    "Withdrawer",
    "account_problem",
    "destination_problem",
    "has_pending",
    "page_view",
    "saved_state",
    "withdrawable_lamports",
    "withdrawn_lamports",
]

log = get_logger(__name__)

KV_STATE = "withdraw.state"
#: Live SOL sent to the owner so far: ``{"lamports": total, "by_day": {"YYYY-MM-DD": lamports}}`` (fees not
#: included), so the page never shows money the owner took back as a trading loss.
KV_TOTALS = "withdraw.totals"
_TOTAL_DAYS_KEPT = 7
#: The engine runs the ``withdraw`` stage this often (seconds).
STAGE_S = 10.0
#: Coins still open this long after the withdrawal began no longer hold the SOL back.
SELL_WAIT_S = 1800.0
#: After a withdrawal is done (or there was nothing to send), look for new SOL this often.
RECHECK_S = 600.0
#: Paper mode re-reads the wallet and re-prices the transfer this often (5 RPC calls each time).
PAPER_RECHECK_S = 300.0
#: A destination the network says is not a plain wallet is checked again this often (until WITHDRAW_TO changes).
BLOCKED_RECHECK_S = 600.0
#: A pending transfer that is not final yet is re-broadcast (the IDENTICAL transaction) at most this often.
REBROADCAST_S = 20.0
#: After a failure, wait this long before trying again (doubling per failure that cost a fee, up to RETRY_MAX_S).
RETRY_S = 60.0
RETRY_MAX_S = 3600.0
#: The network's fee per signature (paper mode's estimate when the network cannot price the message).
BASE_FEE_LAMPORTS = 5000
#: Rent-exempt minimum of a plain wallet (0 data bytes), when the network cannot say.
RENT_EXEMPT_MIN_LAMPORTS = 890_880
SYSTEM_PROGRAM = "11111111111111111111111111111111"
INCINERATOR = "1nc1nerator11111111111111111111111111111111"
_UNSPENDABLE = frozenset({SYSTEM_PROGRAM, INCINERATOR})
STATUSES = ("selling", "sending", "done", "empty", "blocked", "error", "no_wallet", "paper", "off")
_RPC_ERRORS = (HttpError, RpcError, ValueError, TypeError, KeyError, AttributeError)
ERROR_MAX = 160


# =========================================================================== pure rules


def withdrawable_lamports(balance: int, fee: int, rent_exempt_min: int) -> int:
    """Lamports a drain-everything transfer can send: ``balance - fee`` (the wallet ends at exactly 0), or 0 when
    that is not positive or is under ``rent_exempt_min`` (the runtime refuses a fee payer left with a non-zero
    balance below the rent-exempt minimum after the fee). Nothing is ever left behind when the result is > 0."""
    for name, value in (("balance", balance), ("fee", fee), ("rent_exempt_min", rent_exempt_min)):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{name} must be a whole number >= 0, got {value!r}")
    amount = balance - fee
    return amount if amount > 0 and amount >= rent_exempt_min else 0


def _on_curve(address: str) -> bool | None:
    """True/False when ``solders`` can tell whether ``address`` is an ed25519 point (a wallet), else None."""
    try:
        from solders.pubkey import Pubkey
    except ImportError:  # pragma: no cover - the live extra is in the image
        return None
    return bool(Pubkey.from_string(address).is_on_curve())


def destination_problem(to: str, own: str | None) -> str | None:
    """Why ``to`` must not receive the withdrawal, judged without the network (plain words), or None."""
    if not is_pubkey(to):
        return "WITHDRAW_TO is not a Solana address. In Phantom tap Receive, choose Solana and copy the address."
    if own and to == own:
        return "WITHDRAW_TO is the bot's own address. Put YOUR address there (Phantom: Receive, Solana, copy)."
    if to in _UNSPENDABLE:
        return "WITHDRAW_TO is a special Solana address nobody can spend from. Put your Phantom address there."
    if _on_curve(to) is False:
        return ("WITHDRAW_TO is not a wallet address (it looks like a token account or a program). In Phantom tap "
                "Receive, choose Solana and copy that address.")
    return None


def account_problem(info: Any) -> str | None:
    """Why the EXISTING account ``info`` (``getAccountInfo`` value; None = no account yet, which is fine) must not
    receive SOL: a program, an account owned by a program (a token account), or one that holds data."""
    if info is None:
        return None
    if not isinstance(info, dict):
        return "WITHDRAW_TO could not be checked (an unreadable answer from the network)."
    data = info.get("data")
    encoded = data[0] if isinstance(data, list) and data else data
    if (info.get("executable") or info.get("owner") != SYSTEM_PROGRAM
            or (isinstance(encoded, str) and encoded)):
        return ("WITHDRAW_TO is not a plain wallet (it belongs to a program, e.g. a token account): money sent there "
                "could get stuck. In Phantom tap Receive, choose Solana and copy that address.")
    return None


def _day(ts: float) -> str:
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).date().isoformat()


def withdrawn_lamports(ledger: Any, now: float) -> tuple[int, int]:
    """``(all time, today UTC)`` lamports confirmed sent to the owner (kv :data:`KV_TOTALS`)."""
    totals = ledger.get_kv(KV_TOTALS)
    if not isinstance(totals, dict):
        return 0, 0
    total, today = totals.get("lamports"), (totals.get("by_day") or {}).get(_day(now))
    ok = [v if isinstance(v, int) and not isinstance(v, bool) and v > 0 else 0 for v in (total, today)]
    return ok[0], ok[1]


def _count_withdrawn(ledger: Any, lamports: int, now: float) -> None:
    totals = ledger.get_kv(KV_TOTALS)
    totals = totals if isinstance(totals, dict) else {}
    by_day = {str(k): v for k, v in (totals.get("by_day") or {}).items() if isinstance(v, int)}
    by_day[_day(now)] = by_day.get(_day(now), 0) + lamports
    previous = totals.get("lamports")
    previous = previous if isinstance(previous, int) and not isinstance(previous, bool) else 0
    ledger.set_kv(KV_TOTALS, {"lamports": previous + lamports,
                              "by_day": dict(sorted(by_day.items())[-_TOTAL_DAYS_KEPT:])})


def saved_state(ledger: Any) -> dict[str, Any] | None:
    state = ledger.get_kv(KV_STATE)
    return state if isinstance(state, dict) else None


def has_pending(ledger: Any) -> bool:
    """True while a sent transfer is not final yet (it is followed up even after WITHDRAW_TO was deleted)."""
    state = saved_state(ledger)
    return bool(state and isinstance(state.get("pending"), dict))


# =========================================================================== network reads (Solana JSON-RPC)


def _int(value: Any, method: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise RpcError(None, f"{method} returned no number", method)
    return value


def _latest_blockhash(rpc: Any) -> tuple[str, int]:
    result = rpc.call("getLatestBlockhash", [{"commitment": "confirmed"}])
    value = result.get("value") if isinstance(result, dict) else None
    if not isinstance(value, dict) or not isinstance(value.get("blockhash"), str) or not value["blockhash"]:
        raise RpcError(None, "getLatestBlockhash returned no blockhash", "getLatestBlockhash")
    return value["blockhash"], _int(value.get("lastValidBlockHeight"), "getLatestBlockhash")


def _fee_for(rpc: Any, message_b64: str) -> int:
    result = rpc.call("getFeeForMessage", [message_b64, {"commitment": "confirmed"}])
    return _int(result.get("value") if isinstance(result, dict) else None, "getFeeForMessage")


def _rent_exempt_min(rpc: Any) -> int:
    return _int(rpc.call("getMinimumBalanceForRentExemption", [0]), "getMinimumBalanceForRentExemption")


def _finalized_height(rpc: Any) -> int:
    return _int(rpc.call("getBlockHeight", [{"commitment": "finalized"}]), "getBlockHeight")


def _account(rpc: Any, address: str) -> Any:
    result = rpc.call("getAccountInfo", [address, {"encoding": "base64", "commitment": "confirmed"}])
    if not isinstance(result, dict):
        raise RpcError(None, "getAccountInfo returned no result", "getAccountInfo")
    return result.get("value")


def _clean(value: Any) -> Any:
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(k): _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    return value


# =========================================================================== the stage


class Withdrawer:
    """The engine's ``withdraw`` stage (see the module docstring). ``wallet``: the bot's
    :class:`~nightcrawler.broker.wallet.Wallet` (None = no wallet); ``rpc``: a ``SolanaRpc``."""

    #: How often the engine runs the stage (seconds).
    stage_s = STAGE_S

    def __init__(self, settings: Settings, ledger: Any, rpc: Any, wallet: Any, clock: Any = None) -> None:
        self.settings = settings
        self.ledger = ledger
        self.rpc = rpc
        self.wallet = wallet
        self.clock = clock

    # ------------------------------------------------------------------ entry point
    def run(self, now: float, *, open_positions: int = 0, pending_swaps: int = 0) -> str:
        """One step; returns the status. A transfer in flight is always followed up first (even after
        WITHDRAW_TO was deleted) and nothing else happens until the chain has a final answer for it."""
        state = saved_state(self.ledger) or {}
        if isinstance(state.get("pending"), dict):  # also in paper mode (read-only there: never re-broadcast)
            self._follow(state, now)
            if state.get("pending"):
                return str(state.get("status"))
        target = self.settings.withdraw_to
        if not target:
            if state and state.get("status") != "off":
                return self._set(state, now, "off")
            return "off"
        mode = self.settings.trading_mode
        if state.get("to") != target or state.get("mode") != mode or state.get("status") in (None, "off"):
            state = self._fresh(state, now)
            log.warning("withdraw_start to=%s mode=%s: buying nothing, selling everything, then sending all SOL",
                        target, mode)
        state["open_positions"] = int(open_positions)
        if self.wallet is None:
            return self._set(state, now, "no_wallet")
        problem = destination_problem(target, self.wallet.pubkey())
        if problem:
            return self._set(state, now, "blocked", problem)
        if (open_positions or pending_swaps) and now - float(state["since"]) < SELL_WAIT_S:
            state["pending_swaps"] = int(pending_swaps)
            return self._set(state, now, "selling")
        for gate in ("retry_at", "next_check_at"):
            when = state.get(gate)
            if isinstance(when, (int, float)) and now < when:
                return str(state.get("status"))
        if not self.settings.is_live:
            return self._simulate(state, now)
        return self._withdraw(state, now)

    # ------------------------------------------------------------------ paper: show, never sign, never send
    def _simulate(self, state: dict[str, Any], now: float) -> str:
        source, target = self.wallet.pubkey(), self.settings.withdraw_to
        try:
            balance = _int(self.rpc.get_balance(source), "getBalance")
        except _RPC_ERRORS as exc:
            return self._failed(state, now, f"the bot wallet could not be read ({type(exc).__name__})", paid=False)
        fee, exact = BASE_FEE_LAMPORTS, False
        try:
            blockhash, _ = _latest_blockhash(self.rpc)
            fee, exact = _fee_for(self.rpc, transfer_message_b64(source, target, max(balance, 1), blockhash)), True
        except (*_RPC_ERRORS, BrokerError) as exc:  # an estimate is fine for a simulation
            log.info("withdraw_paper_fee_estimated error=%s", type(exc).__name__)
        try:
            rent_min = _rent_exempt_min(self.rpc)
            problem = account_problem(_account(self.rpc, target))
        except _RPC_ERRORS:
            rent_min, problem = RENT_EXEMPT_MIN_LAMPORTS, None
        if problem:
            state["retry_at"] = now + BLOCKED_RECHECK_S
            return self._set(state, now, "blocked", problem)
        amount = withdrawable_lamports(balance, fee, rent_min)
        state["paper"] = {"balance_lamports": balance, "fee_lamports": fee, "fee_exact": exact,
                          "would_send_lamports": amount, "checked_at": now}
        state["next_check_at"] = now + PAPER_RECHECK_S
        state["retry_at"] = None
        noted = [target, amount]
        if state.get("noted") == noted:
            return self._set(state, now, "paper")
        state["noted"] = noted
        with self.ledger.transaction():
            self.ledger.append_receipt("note", {"event": "withdraw_simulated", "mode": "paper", "from": source,
                                                "to": target, "would_send_lamports": amount, "fee_lamports": fee,
                                                "balance_lamports": balance}, ts=now)
            status = self._set(state, now, "paper")
        log.info("withdraw_simulated to=%s would_send_sol=%.9f fee_lamports=%d: paper mode sends nothing", target,
                 amount / LAMPORTS_PER_SOL, fee)
        return status

    # ------------------------------------------------------------------ live: one transfer, exactly once
    def _withdraw(self, state: dict[str, Any], now: float) -> str:
        source, target = self.wallet.pubkey(), self.settings.withdraw_to
        try:
            problem = account_problem(_account(self.rpc, target))
            if problem:
                state["retry_at"] = now + BLOCKED_RECHECK_S
                return self._set(state, now, "blocked", problem)
            balance = _int(self.rpc.get_balance(source), "getBalance")
            rent_min = _rent_exempt_min(self.rpc)
            blockhash, last_valid = _latest_blockhash(self.rpc)
            fee = _fee_for(self.rpc, transfer_message_b64(source, target, max(balance, 1), blockhash))
        except _RPC_ERRORS as exc:
            return self._failed(state, now, f"the network could not be read ({type(exc).__name__})", paid=False)
        amount = withdrawable_lamports(balance, fee, rent_min)
        if amount <= 0:
            state["left_lamports"] = balance
            state["next_check_at"] = now + RECHECK_S
            state["retry_at"] = None
            return self._set(state, now, "done" if state.get("sent_lamports") else "empty")
        signed = sign_transfer(self.wallet, target, amount, blockhash)
        try:
            if _fee_for(self.rpc, signed.message_b64) != fee:  # the fee never depends on the amount; checked anyway
                return self._failed(state, now, "the network fee changed while signing", paid=False)
            err = self.rpc.simulate(signed.tx_b64).get("err")
        except _RPC_ERRORS as exc:  # fail closed: nothing is sent unchecked
            return self._failed(state, now, f"the transfer could not be checked first ({type(exc).__name__})",
                                paid=False)
        if err is not None:
            self.ledger.append_receipt("note", {"event": "withdraw_failed", "stage": "simulate", "to": target,
                                                "lamports": amount, "error": str(err)[:ERROR_MAX]}, ts=now)
            return self._failed(state, now, "the network would refuse the transfer", paid=False)
        pending = {"signature": signed.signature, "tx_b64": signed.tx_b64, "last_valid_block_height": last_valid,
                   "lamports": amount, "fee_lamports": fee, "to": target, "from": source,
                   "balance_lamports": balance, "built_at": now, "sent_at": None, "broadcasts": 0}
        state["pending"] = pending
        state["retry_at"] = state["next_check_at"] = None
        with self.ledger.transaction():  # write-ahead: recorded BEFORE anything leaves the machine
            self.ledger.append_receipt("note", {"event": "withdraw_sending", "mode": "live", "from": source,
                                                "to": target, "lamports": amount, "fee_lamports": fee,
                                                "signature": signed.signature}, ts=now)
            self._set(state, now, "sending")
        log.warning("withdraw_sending to=%s sol=%.9f fee_lamports=%d signature=%s", target, amount / LAMPORTS_PER_SOL,
                    fee, signed.signature)
        self._broadcast(state, now)
        return "sending"

    def _broadcast(self, state: dict[str, Any], now: float) -> None:
        """Post the IDENTICAL pending transaction (safe to repeat: one signature executes at most once)."""
        pending = state["pending"]
        pending["sent_at"] = now
        pending["broadcasts"] = int(pending.get("broadcasts") or 0) + 1
        self._save(state, now)
        try:
            self.rpc.call("sendTransaction", [pending["tx_b64"], {"encoding": "base64", "skipPreflight": True,
                                                                  "maxRetries": 5}])
        except _RPC_ERRORS as exc:  # it may have left anyway: the signature status decides
            log.warning("withdraw_broadcast_failed signature=%s error=%s", pending["signature"], type(exc).__name__)

    def _follow(self, state: dict[str, Any], now: float) -> None:
        """Settle the pending transfer from the chain (see the module docstring)."""
        pending = state["pending"]
        signature = str(pending.get("signature"))
        try:
            status = self.rpc.signature_status(signature)
        except _RPC_ERRORS as exc:
            log.warning("withdraw_status_unavailable signature=%s error=%s", signature, type(exc).__name__)
            return
        final = final_swap_status(status)
        if final == "landed":
            self._landed(state, pending, now)
            return
        if final == "failed":
            error = str((status or {}).get("err"))[:ERROR_MAX]
            state["pending"] = None
            with self.ledger.transaction():
                self.ledger.append_receipt("note", {"event": "withdraw_failed", "stage": "chain",
                                                    "signature": signature, "to": pending.get("to"),
                                                    "lamports": pending.get("lamports"), "error": error}, ts=now)
                self._failed(state, now, "the network refused the transfer", paid=True)
            log.error("withdraw_failed_on_chain signature=%s error=%s", signature, error)
            return
        if status is not None:
            return  # seen in a block, not final yet: wait for the chain
        try:
            height = _finalized_height(self.rpc)
        except _RPC_ERRORS as exc:
            log.warning("withdraw_height_unavailable error=%s", type(exc).__name__)
            return
        if height > int(pending.get("last_valid_block_height") or 0):
            state["pending"] = None  # its blockhash is dead and the chain never saw it: it can never land
            state["retry_at"] = None
            with self.ledger.transaction():
                self.ledger.append_receipt("note", {"event": "withdraw_expired", "signature": signature,
                                                    "to": pending.get("to"), "lamports": pending.get("lamports")},
                                           ts=now)
                self._save(state, now)
            log.warning("withdraw_expired signature=%s: never landed; a new transfer is built from the balance",
                        signature)
            return
        sent_at = pending.get("sent_at")
        if self.settings.is_live and (not isinstance(sent_at, (int, float)) or now - sent_at >= REBROADCAST_S):
            self._broadcast(state, now)

    def _landed(self, state: dict[str, Any], pending: dict[str, Any], now: float) -> None:
        lamports = int(pending.get("lamports") or 0)
        last = {"to": pending.get("to"), "lamports": lamports, "signature": pending.get("signature"),
                "fee_lamports": pending.get("fee_lamports"), "at": now}
        state["pending"] = None
        state["last"] = last
        if pending.get("to") == state.get("to"):
            state["sent_lamports"] = int(state.get("sent_lamports") or 0) + lamports
        state["failures"] = 0
        state["retry_at"] = state["next_check_at"] = None  # look at once whether anything is left
        with self.ledger.transaction():
            self.ledger.append_receipt("withdraw", {"mode": "live", "from": pending.get("from"),
                                                    "to": pending.get("to"), "lamports": lamports,
                                                    "fee_lamports": pending.get("fee_lamports"),
                                                    "signature": pending.get("signature")}, ts=now)
            _count_withdrawn(self.ledger, lamports, now)
            self._set(state, now, "done")
        log.warning("withdraw_done to=%s sol=%.9f signature=%s", pending.get("to"), lamports / LAMPORTS_PER_SOL,
                    pending.get("signature"))

    # ------------------------------------------------------------------ state
    def _fresh(self, previous: dict[str, Any], now: float) -> dict[str, Any]:
        return {"to": self.settings.withdraw_to, "mode": self.settings.trading_mode, "since": now, "status": None,
                "error": None, "updated_at": now, "open_positions": 0, "pending_swaps": 0, "pending": None,
                "failures": 0, "retry_at": None, "next_check_at": None, "sent_lamports": 0, "left_lamports": None,
                "paper": None, "noted": None, "last": previous.get("last")}

    def _failed(self, state: dict[str, Any], now: float, error: str, *, paid: bool) -> str:
        """Try again later: :data:`RETRY_S`, doubling per failure that cost a network fee."""
        if paid:
            state["failures"] = int(state.get("failures") or 0) + 1
        failures = int(state.get("failures") or 0)
        state["retry_at"] = now + min(RETRY_MAX_S, RETRY_S * 2 ** max(0, failures - 1))
        log.warning("withdraw_retry_later error=%s failures=%d", error, failures)
        return self._set(state, now, "error", error)

    def _set(self, state: dict[str, Any], now: float, status: str, error: str | None = None) -> str:
        state["status"] = status
        state["error"] = error[:ERROR_MAX] if error else None
        self._save(state, now)
        return status

    def _save(self, state: dict[str, Any], now: float) -> None:
        state["updated_at"] = now
        self.ledger.set_kv(KV_STATE, _clean(state))


# =========================================================================== the page


def _sol(lamports: Any) -> str:
    if isinstance(lamports, bool) or not isinstance(lamports, int):
        return "?"
    return f"{lamports / LAMPORTS_PER_SOL:.6f}".rstrip("0").rstrip(".") or "0"


def _short(address: Any) -> str:
    text = str(address or "")
    return f"{text[:4]}…{text[-4:]}" if len(text) > 12 else text


def _coins(n: int) -> str:
    return f"{n} coin{'' if n == 1 else 's'}"


def page_view(settings: Settings, state: dict[str, Any] | None, now: float) -> dict[str, Any] | None:
    """The withdrawal as the page shows it - ``{"status", "to", "level": "bad"|"warn", "text"}`` - or None
    when WITHDRAW_TO is not set. ``bad`` (red) while it is still under way, ``warn`` once there is a result."""
    target = settings.withdraw_to
    if not target:
        return None
    to = _short(target)
    if not state or state.get("to") != target or state.get("mode") != settings.trading_mode \
            or state.get("status") in (None, "off"):
        return {"status": "starting", "to": target, "level": "bad",
                "text": f"Withdrawing everything to {to}: starting. The bot buys nothing while WITHDRAW_TO is set."}
    status, error = str(state.get("status")), state.get("error") or ""
    open_n = int(state.get("open_positions") or 0)
    stay = f" {_coins(open_n)} could not be sold and stay in the bot wallet." if open_n else ""
    pending = state.get("pending") if isinstance(state.get("pending"), dict) else None
    retry = state.get("retry_at")
    wait = f" Trying again in about {max(1, round((retry - now) / 60))} min." \
        if isinstance(retry, (int, float)) and retry > now else " Trying again soon."
    paused = " The bot buys nothing while WITHDRAW_TO is set: delete it in Railway to trade again."
    if status == "selling":
        doing = f"selling {_coins(open_n)} first" if open_n else "waiting for a trade to settle first"
        text, level = f"Withdrawing everything to {to}: {doing}, buying nothing.", "bad"
    elif status == "sending" and pending:
        text, level = (f"Withdrawing: sent {_sol(pending.get('lamports'))} SOL to {to}, waiting for the network to "
                       "confirm."), "bad"
    elif status == "done":
        text, level = (f"Withdrawal done: {_sol(state.get('sent_lamports'))} SOL went to {to} (check Phantom)."
                       + stay + paused), "warn"
    elif status == "empty":
        text, level = f"Nothing to withdraw: the bot wallet has no SOL left to send to {to}." + stay + paused, "warn"
    elif status == "blocked":
        text, level = f"Can't withdraw: {error}", "bad"
    elif status == "error":
        text, level = f"Withdrawing to {to}: the last try did not work ({error}).{wait}", "bad"
    elif status == "no_wallet":
        text, level = "WITHDRAW_TO is set, but there is no bot wallet: nothing to send." + paused, "warn"
    elif status == "paper":
        found = state.get("paper")
        paper: dict[str, Any] = found if isinstance(found, dict) else {}
        if paper.get("would_send_lamports"):
            text = (f"Practice mode: the bot would send {_sol(paper.get('would_send_lamports'))} SOL to {to} (network "
                    f"fee {_sol(paper.get('fee_lamports'))} SOL). Nothing was sent. To really send it, also set "
                    "TRADING_MODE=live and LIVE_CONFIRM in Railway: the bot still buys nothing while WITHDRAW_TO is "
                    "set.")
        else:
            text = (f"Practice mode: nothing to send to {to}: the bot wallet holds "
                    f"{_sol(paper.get('balance_lamports'))} SOL, too little to move after the network fee. The bot "
                    "buys nothing while WITHDRAW_TO is set.")
        level = "warn"
    else:
        text, level = f"Withdrawing everything to {to}: working on it.", "bad"
    return {"status": status, "to": target, "level": level, "text": text}


def last_withdrawal(state: dict[str, Any] | None) -> dict[str, Any] | None:
    """The last CONFIRMED real withdrawal ``{"sol", "to", "at", "signature"}`` (kept after WITHDRAW_TO is gone)."""
    last = state.get("last") if isinstance(state, dict) else None
    if not isinstance(last, dict) or not isinstance(last.get("lamports"), int):
        return None
    return {"sol": last["lamports"] / LAMPORTS_PER_SOL, "to": str(last.get("to") or ""), "at": last.get("at"),
            "signature": str(last.get("signature") or "")}
