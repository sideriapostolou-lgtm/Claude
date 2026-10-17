"""WITHDRAW_TO: take everything back without anybody touching a key (owner: O5).

While ``WITHDRAW_TO`` (a Solana address: normally the owner's Phantom wallet) is set:

1. NO BUYS, SELL EVERYTHING. The engine treats it as ``KILL_SWITCH=sell_all`` (``Engine.handle_kill``): every
   position leaves through the usual live exit path (forced exits with the wide impact cap, write-offs,
   reconciliation of unknown swaps).
2. THE DESTINATION IS CHECKED FIRST (:func:`destination_problem`, :func:`account_problem`, :func:`funded_by`).
   Solana addresses have no checksum, so a cut-off, wrong-case or look-alike address is usually a valid
   address of nobody. It must be an EXISTING plain wallet that sent the bot wallet at least
   :data:`MIN_FUNDING_LAMPORTS` in one SystemProgram transfer (found in both addresses' recent history:
   :data:`FUNDER_PAGES` pages each). The dust an address-poisoning look-alike sends is far below that.
3. TEN MINUTES TO CANCEL (live). Nothing is signed until :data:`ARM_S` after the destination was accepted; the
   page shows the FULL address and the amount meanwhile, and deleting WITHDRAW_TO cancels.
4. EMPTY COIN ACCOUNTS ARE CLOSED (live). Ultra leaves emptied token accounts open (``broker/base.py``) and
   nobody but this code can sign for the bot wallet, so before each sweep the bot closes its token accounts
   holding 0 coins (SPL Token and Token-2022; :func:`nightcrawler.broker.keystore.sign_close_accounts`),
   each deposit (~0.002 SOL) returning to the bot wallet. A ``note`` ``accounts_closed`` records what came
   back (the audit counts it). Frozen accounts, and ones the network refuses to close in a simulation, stay.
   Coins that could not be sold stay in the wallet (their accounts are not empty).
5. THEN ALL THE SOL in ONE SystemProgram transfer signed by the keystore
   (:func:`nightcrawler.broker.keystore.sign_transfer`), simulated first, confirmed on chain, then receipted
   (kind ``withdraw``: from, to, lamports, signature, fee). Later SOL (a late sale, a new deposit) is swept
   the same way every :data:`RECHECK_S` while WITHDRAW_TO stays set.

AMOUNT (:func:`withdrawable_lamports`): ``balance - fee - reserve``, where the fee is what the network charges
for that exact message (``getFeeForMessage``: 5000 lamports per signature, no priority fee). The reserve is 0
once nothing is left to sell: the bot wallet pays the fee and ends at exactly 0 lamports, which the runtime
allows (the account is closed). While coins, unresolved swaps or wallet/books differences remain
:data:`SELL_WAIT_S` after the withdrawal began (a coin nobody will buy cannot hold the SOL hostage), the
sweep keeps :func:`reserve_lamports` back - enough to pay for selling each of them and one temporary wSOL
account - and the rest follows once they are gone. The runtime refuses a fee payer left with a NON-zero balance
under the rent-exempt minimum (``getMinimumBalanceForRentExemption(0)``, 890,880 lamports), so a reserve is
never smaller than that and an amount under that minimum (under ~0.0009 SOL) is not sent.

LIVE START (W4): a withdrawal before the engine recorded the wallet's starting SOL (kv
``live.start_lamports``: it needs the SOL price) records it itself from the balance, BEFORE closing or
sending anything, so the money card and the audit never count the owner's own money as profit or as missing.

EXACTLY ONCE, across restarts (kv :data:`KV_STATE`):

* write-ahead: the signed transaction (no key in it; anybody may broadcast it, and it can only pay WITHDRAW_TO),
  its signature and its blockhash's ``lastValidBlockHeight`` are saved in ``pending`` together with a ``note``
  ``withdraw_sending`` receipt BEFORE the first broadcast;
* while ``pending``, only that IDENTICAL transaction is re-broadcast (one signature: it cannot execute twice)
  every :data:`REBROADCAST_S` until ``getSignatureStatuses`` is final - and only while WITHDRAW_TO still
  names its destination (deleting it is the way to stop). Nothing is bought while a transfer is pending.
  A NEW transfer is built only when it failed on chain, or when its blockhash is dead at the FINALIZED block
  height and neither the status nor ``getTransaction`` (finalized) knows it; such an expired transfer is kept
  in ``expired`` and checked again for :data:`EXPIRED_WATCH_S` (two RPC nodes can disagree), and receipted if
  it turns out to have landed after all;
* every amount is read from the wallet right before signing, so even two transfers could never pay twice.

AFTER A LIVE WITHDRAWAL (kv :data:`KV_HOLD`): the bot buys nothing with real money once WITHDRAW_TO is deleted
(kill mode ``stop``) until it has run in PAPER mode once, so a later deposit through the same "To fund" card
is never traded by surprise without the readiness steps.

PAPER MODE never signs and never sends: it checks the destination, reads the real wallet's balance and token
accounts, prices the transfer with an UNSIGNED message and shows what it would send (``note``
``withdraw_simulated`` when that changes). Paper positions are still sold (simulated) first.

kv ``withdraw.state`` = ``{"to", "mode", "since", "status", "error", "updated_at", "open_positions",
"pending_swaps", "drift", "dest_ok", "dest_ok_at", "preview": {"balance_lamports", "at"}|None,
"pending": {...}|None, "closing": {...}|None, "unclosable": [...], "close_failures", "expired": [...],
"failures", "retry_at", "next_check_at", "sent_lamports", "left_lamports", "reserve_lamports",
"balance_after": {"lamports", "at"}|None, "paper": {...}|None, "noted", "last": {...}|None}``; ``status`` is
one of :data:`STATUSES`.
"""

from __future__ import annotations

import math
from typing import Any

from nightcrawler.base58 import is_pubkey
from nightcrawler.broker.base import BrokerError
from nightcrawler.broker.keystore import TOKEN_PROGRAMS, sign_close_accounts, sign_transfer, transfer_message_b64
from nightcrawler.broker.live import final_swap_status
from nightcrawler.config import LIVE_CONFIRM_PHRASE, Settings, dashboard_token_problem
from nightcrawler.http import HttpError
from nightcrawler.logging_setup import get_logger
from nightcrawler.models import LAMPORTS_PER_SOL, TOKEN_ACCOUNT_RENT_LAMPORTS
from nightcrawler.sources.solana_rpc import RpcError

__all__ = [
    "ARM_S",
    "BASE_FEE_LAMPORTS",
    "KV_HOLD",
    "KV_STATE",
    "MIN_FUNDING_LAMPORTS",
    "RENT_EXEMPT_MIN_LAMPORTS",
    "SELL_WAIT_S",
    "STAGE_S",
    "STATUSES",
    "TOKEN_2022_PROGRAM",
    "TOKEN_PROGRAM",
    "Withdrawer",
    "account_problem",
    "destination_problem",
    "funded_by",
    "has_pending",
    "live_hold",
    "page_view",
    "reserve_lamports",
    "saved_state",
    "withdrawable_lamports",
    "withdrawn_lamports",
]

log = get_logger(__name__)

KV_STATE = "withdraw.state"
#: Live SOL sent to the owner: ``{"lamports": total, "events": [[landed at, lamports], ...]}`` (fees not
#: included; the last :data:`_EVENTS_KEPT` landings), so the page never shows money the owner took back as a
#: trading loss - and adds back only what an equity point already reflects.
KV_TOTALS = "withdraw.totals"
_EVENTS_KEPT = 1000
#: Set when a LIVE withdrawal starts; cleared by the first run in paper mode (see the module docstring).
KV_HOLD = "withdraw.live_hold"
#: The engine runs the ``withdraw`` stage this often (seconds).
STAGE_S = 10.0
#: Live: nothing is signed until this long after the destination was accepted (the owner can still cancel).
ARM_S = 600.0
#: While arming, the balance shown on the page is read again at most this often.
PREVIEW_S = 60.0
#: Coins still open this long after the withdrawal began no longer hold back the SOL beyond the reserve.
SELL_WAIT_S = 1800.0
#: After a withdrawal is done (or there was nothing to send), look for new SOL this often.
RECHECK_S = 600.0
#: Paper mode re-reads the wallet and re-prices the transfer this often.
PAPER_RECHECK_S = 300.0
#: A destination that was refused is checked again this often (until WITHDRAW_TO changes).
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
#: The smallest single transfer from WITHDRAW_TO to the bot wallet that shows it is the owner's (0.01 SOL).
MIN_FUNDING_LAMPORTS = 10_000_000
#: Pages of 1000 signatures searched in each address's history for that transfer, and transactions fetched.
FUNDER_PAGES = 3
FUNDER_TX_MAX = 25
#: Kept back per coin still to sell after SELL_WAIT_S (network + priority fee, generously) ...
SWAP_RESERVE_LAMPORTS = 2_000_000
#: ... plus one temporary wSOL account (a sell to SOL opens and closes one in the same transaction).
WSOL_RENT_LAMPORTS = TOKEN_ACCOUNT_RENT_LAMPORTS
#: CloseAccount instructions per transaction, and attempts before the sweep goes ahead without closing.
CLOSE_BATCH = 8
CLOSE_TRIES = 3
#: An expired transfer is checked again this often, for this long (two RPC nodes can disagree).
EXPIRED_CHECK_S = 60.0
EXPIRED_WATCH_S = 86_400.0
SYSTEM_PROGRAM = "11111111111111111111111111111111"
INCINERATOR = "1nc1nerator11111111111111111111111111111111"
TOKEN_PROGRAM, TOKEN_2022_PROGRAM = TOKEN_PROGRAMS
_UNSPENDABLE = frozenset({SYSTEM_PROGRAM, INCINERATOR})
STATUSES = ("selling", "arming", "closing", "sending", "done", "empty", "blocked", "error", "no_wallet", "paper",
            "off")
_RPC_ERRORS = (HttpError, RpcError, ValueError, TypeError, KeyError, AttributeError)
ERROR_MAX = 400
_NEVER_FUNDED = ("WITHDRAW_TO never sent SOL to the bot wallet (at least 0.01 SOL in one go), so the bot will not "
                 "send everything there: a wrong or look-alike address would lose it all. Put the Phantom address "
                 "you funded the bot from (Phantom: Receive, Solana, copy). Sent from it long ago? Send 0.01 SOL "
                 "from it to the bot again and wait 10 minutes.")


# =========================================================================== pure rules


def withdrawable_lamports(balance: int, fee: int, rent_exempt_min: int, reserve: int = 0) -> int:
    """Lamports one transfer can send: ``balance - fee - reserve`` - with ``reserve`` 0 the wallet ends at exactly
    0 - or 0 when that is not positive or is under ``rent_exempt_min`` (the runtime refuses a fee payer left with
    a non-zero balance below the rent-exempt minimum after the fee). A reserve is never smaller than
    ``rent_exempt_min``, so what stays behind is always 0 or rent-exempt."""
    for name, value in (("balance", balance), ("fee", fee), ("rent_exempt_min", rent_exempt_min),
                        ("reserve", reserve)):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{name} must be a whole number >= 0, got {value!r}")
    keep = max(reserve, rent_exempt_min) if reserve else 0
    amount = balance - fee - keep
    return amount if amount > 0 and amount >= rent_exempt_min else 0


def reserve_lamports(unsold: int) -> int:
    """SOL kept in the bot wallet while ``unsold`` coins/swaps are left: enough to pay for selling each of them
    (and one more), plus one temporary wSOL account. 0 when nothing is left to sell."""
    if unsold <= 0:
        return 0
    return WSOL_RENT_LAMPORTS + (unsold + 1) * SWAP_RESERVE_LAMPORTS


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
    """Why the account ``info`` (``getAccountInfo`` value) must not receive SOL: it does not exist (None: nobody
    ever used that address, so it is a typo, not the owner's wallet), it is a program, it belongs to a program
    (a token account) or it holds data."""
    if info is None:
        return ("WITHDRAW_TO does not exist on Solana (no wallet ever used it): it is mistyped or cut off. In Phantom "
                "tap Receive, choose Solana and copy the address again.")
    if not isinstance(info, dict):
        return "WITHDRAW_TO could not be checked (an unreadable answer from the network)."
    data = info.get("data")
    encoded = data[0] if isinstance(data, list) and data else data
    if (info.get("executable") or info.get("owner") != SYSTEM_PROGRAM
            or (isinstance(encoded, str) and encoded)):
        return ("WITHDRAW_TO is not a plain wallet (it belongs to a program, e.g. a token account): money sent there "
                "could get stuck. In Phantom tap Receive, choose Solana and copy that address.")
    return None


def _funding_lamports(tx: Any, source: str, dest: str) -> int:
    """The largest single SystemProgram transfer ``source`` -> ``dest`` in a successful ``jsonParsed`` transaction."""
    meta = tx.get("meta") if isinstance(tx, dict) else None
    if not isinstance(meta, dict) or meta.get("err") is not None:
        return 0
    message = (tx.get("transaction") or {}).get("message") or {}
    instructions = list(message.get("instructions") or [])
    for inner in meta.get("innerInstructions") or []:
        instructions += list((inner or {}).get("instructions") or [])
    best = 0
    for ix in instructions:
        parsed = ix.get("parsed") if isinstance(ix, dict) and ix.get("program") == "system" else None
        if not isinstance(parsed, dict) or parsed.get("type") not in ("transfer", "transferWithSeed"):
            continue
        info = parsed.get("info") or {}
        lamports = info.get("lamports")
        if (info.get("source") == source and info.get("destination") == dest and isinstance(lamports, int)
                and not isinstance(lamports, bool)):
            best = max(best, lamports)
    return best


def withdrawn_lamports(ledger: Any, until: float | None, day_from: float | None = None) -> tuple[int, int]:
    """Lamports confirmed sent to the owner ``(landed at or before until, landed after day_from and at or before
    until)``, from kv :data:`KV_TOTALS`. The money card passes its latest equity point's time as ``until``
    (a later withdrawal is not in that point yet) and the time of today's first point as ``day_from``."""
    totals = ledger.get_kv(KV_TOTALS)
    if until is None or not isinstance(totals, dict):
        return 0, 0
    events = [(float(e[0]), int(e[1])) for e in totals.get("events") or []
              if isinstance(e, list) and len(e) == 2 and isinstance(e[0], (int, float)) and isinstance(e[1], int)]
    total = totals.get("lamports")
    total = total if isinstance(total, int) and not isinstance(total, bool) else 0
    older = max(0, total - sum(lamports for _, lamports in events))  # dropped from the list: long ago
    upto = older + sum(lamports for ts, lamports in events if ts <= until)
    today = sum(lamports for ts, lamports in events if day_from is not None and day_from < ts <= until)
    return upto, today


def _count_withdrawn(ledger: Any, lamports: int, now: float) -> None:
    totals = ledger.get_kv(KV_TOTALS)
    totals = totals if isinstance(totals, dict) else {}
    events = [e for e in totals.get("events") or [] if isinstance(e, list) and len(e) == 2]
    previous = totals.get("lamports")
    previous = previous if isinstance(previous, int) and not isinstance(previous, bool) else 0
    ledger.set_kv(KV_TOTALS, {"lamports": previous + lamports, "events": [*events, [now, lamports]][-_EVENTS_KEPT:]})


def saved_state(ledger: Any) -> dict[str, Any] | None:
    state = ledger.get_kv(KV_STATE)
    return state if isinstance(state, dict) else None


def has_pending(ledger: Any) -> bool:
    """True while a sent transfer is not final yet (it is followed up even after WITHDRAW_TO was deleted)."""
    state = saved_state(ledger)
    return bool(state and isinstance(state.get("pending"), dict))


def live_hold(ledger: Any) -> dict[str, Any] | None:
    """The hold after a live withdrawal (kv :data:`KV_HOLD`), or None."""
    hold = ledger.get_kv(KV_HOLD)
    return hold if isinstance(hold, dict) else None


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


def _signatures(rpc: Any, address: str) -> list[str]:
    """Successful signatures of ``address``, newest first (at most :data:`FUNDER_PAGES` pages)."""
    out: list[str] = []
    before: str | None = None
    for _ in range(FUNDER_PAGES):
        opts: dict[str, Any] = {"limit": 1000, "commitment": "confirmed"}
        if before:
            opts["before"] = before
        page = rpc.call("getSignaturesForAddress", [address, opts])
        if not isinstance(page, list):
            raise RpcError(None, "getSignaturesForAddress returned no list", "getSignaturesForAddress")
        rows = [r for r in page if isinstance(r, dict) and isinstance(r.get("signature"), str)]
        out += [r["signature"] for r in rows if r.get("err") is None]
        if len(page) < 1000 or not rows:
            break
        before = rows[-1]["signature"]
    return out


def funded_by(rpc: Any, bot: str, source: str) -> bool:
    """True when ``source`` sent ``bot`` at least :data:`MIN_FUNDING_LAMPORTS` in one SystemProgram transfer
    (a transaction both histories list, read with ``getTransaction``). Raises on network trouble."""
    mine = set(_signatures(rpc, bot))
    shared = [sig for sig in _signatures(rpc, source) if sig in mine][:FUNDER_TX_MAX]
    for sig in shared:
        tx = rpc.call("getTransaction", [sig, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0,
                                               "commitment": "confirmed"}])
        if _funding_lamports(tx, source, bot) >= MIN_FUNDING_LAMPORTS:
            return True
    return False


def _empty_token_accounts(rpc: Any, owner: str) -> list[dict[str, Any]]:
    """The bot's token accounts holding 0 coins that it can close: ``[{"address", "program", "lamports"}]``
    (frozen accounts excluded). Raises on network trouble."""
    out = []
    for program in TOKEN_PROGRAMS:
        result = rpc.call("getTokenAccountsByOwner", [owner, {"programId": program},
                                                      {"encoding": "jsonParsed", "commitment": "confirmed"}])
        value = result.get("value") if isinstance(result, dict) else None
        if not isinstance(value, list):
            raise RpcError(None, "getTokenAccountsByOwner returned no list", "getTokenAccountsByOwner")
        for item in value:
            account = item.get("account") if isinstance(item, dict) else None
            if not isinstance(account, dict) or account.get("owner") != program:
                continue
            info = (((account.get("data") or {}).get("parsed") or {}).get("info") or {})
            amount = (info.get("tokenAmount") or {}).get("amount")
            lamports = account.get("lamports")
            if (info.get("owner") == owner and amount == "0" and info.get("state", "initialized") == "initialized"
                    and isinstance(lamports, int) and is_pubkey(str(item.get("pubkey")))):
                out.append({"address": str(item["pubkey"]), "program": program, "lamports": lamports})
    return out


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

    # ------------------------------------------------------------------ the engine's kill switch
    def kill_mode(self, mode: str) -> str:
        """The kill mode with the withdrawal applied (live): ``sell_all`` while a transfer may still land (nothing
        is bought), ``stop`` instead of ``off`` during the hold after a live withdrawal."""
        if self.settings.withdraw_to:
            return "sell_all"
        if not self.settings.is_live:
            return mode
        if has_pending(self.ledger):
            return "sell_all"
        if mode == "off" and live_hold(self.ledger) is not None:
            return "stop"
        return mode

    # ------------------------------------------------------------------ entry point
    def run(self, now: float, *, open_positions: int = 0, pending_swaps: int = 0, drift: int = 0) -> str:
        """One step; returns the status. A transfer in flight is always followed up first (even after
        WITHDRAW_TO was deleted) and nothing else happens until the chain has a final answer for it."""
        if not self.settings.is_live:
            self._clear_hold(now)
        state = saved_state(self.ledger) or {}
        if isinstance(state.get("pending"), dict):  # also in paper mode (read-only there: never re-broadcast)
            self._follow(state, now)
            if state.get("pending"):
                return str(state.get("status"))
        if state.get("expired"):
            self._recheck_expired(state, now)
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
            if self.settings.is_live:
                self.ledger.set_kv(KV_HOLD, {"since": now, "to": target})
        unsold = int(open_positions) + int(pending_swaps) + int(drift)
        state.update(open_positions=int(open_positions), pending_swaps=int(pending_swaps), drift=int(drift))
        if self.wallet is None:
            return self._set(state, now, "no_wallet")
        problem = destination_problem(target, self.wallet.pubkey())
        if problem:
            return self._set(state, now, "blocked", problem)
        for gate in ("retry_at", "next_check_at"):
            when = state.get(gate)
            if isinstance(when, (int, float)) and now < when:
                return str(state.get("status"))
        if state.get("dest_ok") != target:
            status = self._check_destination(state, now)
            if status is not None:
                return status
        if unsold and now - float(state["since"]) < SELL_WAIT_S:
            return self._set(state, now, "selling")
        if self.settings.is_live and now - float(state.get("dest_ok_at") or now) < ARM_S:
            return self._arming(state, now)
        if not self.settings.is_live:
            return self._simulate(state, now, unsold)
        return self._withdraw(state, now, unsold)

    def _check_destination(self, state: dict[str, Any], now: float) -> str | None:
        """Accept WITHDRAW_TO once (it exists, is a plain wallet and funded the bot); a status to return when it
        is refused or cannot be checked. Paper mode goes on unchecked when the network cannot say."""
        target, bot = self.settings.withdraw_to, self.wallet.pubkey()
        try:
            problem = account_problem(_account(self.rpc, target))
            if problem is None and not funded_by(self.rpc, bot, target):
                problem = _NEVER_FUNDED
        except _RPC_ERRORS as exc:
            if not self.settings.is_live:
                log.info("withdraw_paper_destination_unchecked error=%s", type(exc).__name__)
                return None
            return self._failed(state, now, f"WITHDRAW_TO could not be checked yet ({type(exc).__name__})",
                                paid=False)
        if problem:
            state["retry_at"] = now + BLOCKED_RECHECK_S
            log.warning("withdraw_blocked to=%s reason=%s", target, problem[:80])
            return self._set(state, now, "blocked", problem)
        state["dest_ok"], state["dest_ok_at"], state["retry_at"] = target, now, None
        log.info("withdraw_destination_ok to=%s: it exists and funded the bot", target)
        return None

    # ------------------------------------------------------------------ live: ten minutes to cancel
    def _arming(self, state: dict[str, Any], now: float) -> str:
        preview = state.get("preview")
        if not isinstance(preview, dict) or now - float(preview.get("at") or 0) >= PREVIEW_S:
            try:
                state["preview"] = {"balance_lamports": _int(self.rpc.get_balance(self.wallet.pubkey()), "getBalance"),
                                    "at": now}
            except _RPC_ERRORS:
                pass  # only what the page shows meanwhile
        return self._set(state, now, "arming")

    # ------------------------------------------------------------------ paper: show, never sign, never send
    def _simulate(self, state: dict[str, Any], now: float, unsold: int) -> str:
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
        except _RPC_ERRORS:
            rent_min = RENT_EXEMPT_MIN_LAMPORTS
        try:
            empties = _empty_token_accounts(self.rpc, source)
        except _RPC_ERRORS:
            empties = []
        reclaim = sum(int(a["lamports"]) for a in empties)
        close_fee = BASE_FEE_LAMPORTS * math.ceil(len(empties) / CLOSE_BATCH)
        reserve = reserve_lamports(unsold)
        amount = withdrawable_lamports(max(0, balance + reclaim - close_fee), fee, rent_min, reserve)
        state["paper"] = {"balance_lamports": balance, "fee_lamports": fee, "fee_exact": exact,
                          "would_send_lamports": amount, "checked_at": now, "close_accounts": len(empties),
                          "reclaim_lamports": reclaim, "reserve_lamports": reserve}
        state["next_check_at"] = now + PAPER_RECHECK_S
        state["retry_at"] = None
        noted = [target, amount]
        if state.get("noted") == noted:
            return self._set(state, now, "paper")
        state["noted"] = noted
        with self.ledger.transaction():
            self.ledger.append_receipt("note", {"event": "withdraw_simulated", "mode": "paper", "from": source,
                                                "to": target, "would_send_lamports": amount, "fee_lamports": fee,
                                                "balance_lamports": balance, "close_accounts": len(empties),
                                                "reclaim_lamports": reclaim}, ts=now)
            status = self._set(state, now, "paper")
        log.info("withdraw_simulated to=%s would_send_sol=%.9f fee_lamports=%d close_accounts=%d: paper mode sends "
                 "nothing", target, amount / LAMPORTS_PER_SOL, fee, len(empties))
        return status

    # ------------------------------------------------------------------ live: one transfer, exactly once
    def _withdraw(self, state: dict[str, Any], now: float, unsold: int) -> str:
        source, target = self.wallet.pubkey(), self.settings.withdraw_to
        try:
            self._ensure_live_start(now)
        except _RPC_ERRORS as exc:
            return self._failed(state, now, f"the bot wallet could not be read ({type(exc).__name__})", paid=False)
        if not self._close_empty_accounts(state, now):
            return str(state.get("status"))
        try:
            problem = account_problem(_account(self.rpc, target))  # once more, right before signing
            if problem:
                state["retry_at"] = now + BLOCKED_RECHECK_S
                state["dest_ok"] = None
                return self._set(state, now, "blocked", problem)
            balance = _int(self.rpc.get_balance(source), "getBalance")
            rent_min = _rent_exempt_min(self.rpc)
            blockhash, last_valid = _latest_blockhash(self.rpc)
            fee = _fee_for(self.rpc, transfer_message_b64(source, target, max(balance, 1), blockhash))
        except _RPC_ERRORS as exc:
            return self._failed(state, now, f"the network could not be read ({type(exc).__name__})", paid=False)
        reserve = reserve_lamports(unsold)
        amount = withdrawable_lamports(balance, fee, rent_min, reserve)
        state["reserve_lamports"] = reserve
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
                   "lamports": amount, "fee_lamports": fee, "to": target, "from": source, "reserve_lamports": reserve,
                   "balance_lamports": balance, "built_at": now, "sent_at": None, "broadcasts": 0}
        state["pending"] = pending
        state["retry_at"] = state["next_check_at"] = None
        with self.ledger.transaction():  # write-ahead: recorded BEFORE anything leaves the machine
            self.ledger.append_receipt("note", {"event": "withdraw_sending", "mode": "live", "from": source,
                                                "to": target, "lamports": amount, "fee_lamports": fee,
                                                "reserve_lamports": reserve, "signature": signed.signature}, ts=now)
            self._set(state, now, "sending")
        log.warning("withdraw_sending to=%s sol=%.9f fee_lamports=%d reserve_lamports=%d signature=%s", target,
                    amount / LAMPORTS_PER_SOL, fee, reserve, signed.signature)
        self._broadcast(state, now)
        return "sending"

    def _ensure_live_start(self, now: float) -> None:
        """Record kv ``live.start_lamports`` from the wallet when the engine could not yet (W4)."""
        if self.ledger.get_kv("live.start_lamports") is not None or self.ledger.fills_after_seq(0, mode="live"):
            return
        balance = _int(self.rpc.get_balance(self.wallet.pubkey()), "getBalance")
        with self.ledger.transaction():
            self.ledger.set_kv("live.start_lamports", balance)
            self.ledger.append_receipt("note", {"event": "live_start", "start_lamports": balance, "sol_usd": None,
                                                "by": "withdraw"}, ts=now)
        log.warning("live_start_recorded_by_withdraw start_lamports=%d: the engine had not recorded it yet", balance)

    # ------------------------------------------------------------------ live: close empty coin accounts
    def _close_empty_accounts(self, state: dict[str, Any], now: float) -> bool:
        """True when the sweep may go ahead (nothing left to close, or closing gave up after :data:`CLOSE_TRIES`);
        False while a close transaction is on its way (status ``closing``) or failed (``error``, retried)."""
        closing = state.get("closing")
        if isinstance(closing, dict) and not self._follow_close(state, closing, now):
            return False
        if int(state.get("close_failures") or 0) >= CLOSE_TRIES:
            return True
        source = self.wallet.pubkey()
        skip = set(state.get("unclosable") or [])
        try:
            empties = [a for a in _empty_token_accounts(self.rpc, source) if a["address"] not in skip]
            if not empties:
                return True
            batch = empties[:CLOSE_BATCH]
            blockhash, last_valid = _latest_blockhash(self.rpc)
            batch, signed = self._closable(batch, blockhash, state)
            if signed is None:
                return True
            fee = _fee_for(self.rpc, signed.message_b64)
        except _RPC_ERRORS as exc:
            state["close_failures"] = int(state.get("close_failures") or 0) + 1
            self._failed(state, now, f"the empty coin accounts could not be closed ({type(exc).__name__})",
                         paid=False)
            return False
        state["closing"] = {"signature": signed.signature, "tx_b64": signed.tx_b64,
                            "last_valid_block_height": last_valid, "accounts": [a["address"] for a in batch],
                            "fee_lamports": fee,
                            "reclaim_lamports": sum(int(a["lamports"]) for a in batch), "sent_at": now}
        self._set(state, now, "closing")
        log.info("withdraw_closing_accounts count=%d reclaim_lamports=%d signature=%s", len(batch),
                 state["closing"]["reclaim_lamports"], signed.signature)
        self._post(signed.tx_b64, signed.signature)
        return False

    def _closable(self, batch: list[dict[str, Any]], blockhash: str, state: dict[str, Any]) -> tuple[list, Any]:
        """The accounts of ``batch`` the network agrees to close (a simulation each when the whole batch is
        refused; refused ones are remembered in ``unclosable``) and their signed transaction, or ``(batch, None)``."""
        def sign(accounts: list[dict[str, Any]]) -> Any:
            return sign_close_accounts(self.wallet, [(a["address"], a["program"]) for a in accounts], blockhash)

        signed = sign(batch)
        if self.rpc.simulate(signed.tx_b64).get("err") is None:
            return batch, signed
        good = [a for a in batch if self.rpc.simulate(sign([a]).tx_b64).get("err") is None]
        bad = [a["address"] for a in batch if a not in good]
        state["unclosable"] = sorted({*(state.get("unclosable") or []), *bad})
        log.warning("withdraw_accounts_not_closable count=%d: the network refuses to close them", len(bad))
        if not good:
            return batch, None
        signed = sign(good)
        if self.rpc.simulate(signed.tx_b64).get("err") is not None:
            state["unclosable"] = sorted({*state["unclosable"], *(a["address"] for a in good)})
            return batch, None
        return good, signed

    def _follow_close(self, state: dict[str, Any], closing: dict[str, Any], now: float) -> bool:
        """Settle the pending close transaction; True once it is final (landed, failed or dead)."""
        signature = str(closing.get("signature"))
        try:
            status = self.rpc.signature_status(signature)
            final = final_swap_status(status)
            dead = status is None and _finalized_height(self.rpc) > int(closing.get("last_valid_block_height") or 0)
        except _RPC_ERRORS as exc:
            log.warning("withdraw_close_status_unavailable signature=%s error=%s", signature, type(exc).__name__)
            return False
        if final == "landed":
            state["closing"] = None
            with self.ledger.transaction():
                self.ledger.append_receipt("note", {
                    "event": "accounts_closed", "mode": "live", "from": self.wallet.pubkey(),
                    "accounts": len(closing.get("accounts") or []),
                    "reclaimed_lamports": closing.get("reclaim_lamports"),
                    "fee_lamports": closing.get("fee_lamports"), "signature": signature}, ts=now)
                self._save(state, now)
            log.info("withdraw_accounts_closed count=%d reclaimed_lamports=%s", len(closing.get("accounts") or []),
                     closing.get("reclaim_lamports"))
            return True
        if final == "failed" or dead:
            state["closing"] = None
            state["close_failures"] = int(state.get("close_failures") or 0) + 1
            self.ledger.append_receipt("note", {"event": "accounts_close_failed", "signature": signature,
                                                "error": str((status or {}).get("err"))[:ERROR_MAX]
                                                if final == "failed" else "expired"}, ts=now)
            self._save(state, now)
            return True
        if self.settings.withdraw_to and now - float(closing.get("sent_at") or 0) >= REBROADCAST_S:
            closing["sent_at"] = now
            self._save(state, now)
            self._post(str(closing.get("tx_b64")), signature)
        return False

    # ------------------------------------------------------------------ live: broadcast and follow the transfer
    def _post(self, tx_b64: str, signature: str) -> None:
        try:
            self.rpc.call("sendTransaction", [tx_b64, {"encoding": "base64", "skipPreflight": True, "maxRetries": 5}])
        except _RPC_ERRORS as exc:  # it may have left anyway: the signature status decides
            log.warning("withdraw_broadcast_failed signature=%s error=%s", signature, type(exc).__name__)

    def _broadcast(self, state: dict[str, Any], now: float) -> None:
        """Post the IDENTICAL pending transaction (safe to repeat: one signature executes at most once)."""
        pending = state["pending"]
        pending["sent_at"] = now
        pending["broadcasts"] = int(pending.get("broadcasts") or 0) + 1
        self._save(state, now)
        self._post(pending["tx_b64"], pending["signature"])

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
        if final is None and status is None:
            try:
                height = _finalized_height(self.rpc)
                if height <= int(pending.get("last_valid_block_height") or 0):
                    final = "wait"
                else:  # its blockhash is dead: ask for the transaction itself before calling it expired (W5)
                    final = self._fetched_outcome(signature) or "expired"
            except _RPC_ERRORS as exc:
                log.warning("withdraw_height_unavailable error=%s", type(exc).__name__)
                return
        if final == "landed":
            state["pending"] = None
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
        if final == "expired":
            state["pending"] = None  # it can never land now (unless a node was behind: kept in "expired")
            state["retry_at"] = None
            state["expired"] = [*(state.get("expired") or []), {**{k: pending.get(k) for k in (
                "signature", "to", "from", "lamports", "fee_lamports")}, "expired_at": now}][-5:]
            with self.ledger.transaction():
                self.ledger.append_receipt("note", {"event": "withdraw_expired", "signature": signature,
                                                    "to": pending.get("to"), "lamports": pending.get("lamports")},
                                           ts=now)
                self._save(state, now)
            log.warning("withdraw_expired signature=%s: never seen; a new transfer is built from the balance (this "
                        "one is checked again for a day)", signature)
            return
        if status is not None:
            return  # seen in a block, not final yet: wait for the chain
        sent_at = pending.get("sent_at")
        if (self.settings.is_live and self.settings.withdraw_to == pending.get("to")
                and (not isinstance(sent_at, (int, float)) or now - sent_at >= REBROADCAST_S)):
            self._broadcast(state, now)  # only while WITHDRAW_TO still names it: deleting it stops this (W6)

    def _fetched_outcome(self, signature: str) -> str | None:
        """``getTransaction`` (finalized): "landed" / "failed" when the chain has it, else None."""
        tx = self.rpc.call("getTransaction", [signature, {"encoding": "json", "maxSupportedTransactionVersion": 0,
                                                          "commitment": "finalized"}])
        meta = tx.get("meta") if isinstance(tx, dict) else None
        if not isinstance(meta, dict):
            return None
        return "landed" if meta.get("err") is None else "failed"

    def _recheck_expired(self, state: dict[str, Any], now: float) -> None:
        """A transfer called expired may have landed after all (another node was behind): receipt it then."""
        if now - float(state.get("expired_check_at") or 0) < EXPIRED_CHECK_S:
            return
        state["expired_check_at"] = now
        kept = []
        for item in state.get("expired") or []:
            if not isinstance(item, dict):
                continue
            try:
                final = final_swap_status(self.rpc.signature_status(str(item.get("signature"))))
            except _RPC_ERRORS:
                kept.append(item)
                continue
            if final == "landed":
                log.error("withdraw_landed_after_all signature=%s: it was called expired too early",
                          item.get("signature"))
                self._landed(state, item, now, late=True)
            elif final is None and now - float(item.get("expired_at") or now) < EXPIRED_WATCH_S:
                kept.append(item)
        state["expired"] = kept
        self._save(state, now)

    def _landed(self, state: dict[str, Any], pending: dict[str, Any], now: float, late: bool = False) -> None:
        lamports = int(pending.get("lamports") or 0)
        last = {"to": pending.get("to"), "lamports": lamports, "signature": pending.get("signature"),
                "fee_lamports": pending.get("fee_lamports"), "at": now}
        state["last"] = last
        if pending.get("to") == state.get("to"):
            state["sent_lamports"] = int(state.get("sent_lamports") or 0) + lamports
        state["failures"] = 0
        state["retry_at"] = state["next_check_at"] = None  # look at once whether anything is left
        try:  # the wallet card shows this until the next equity snapshot (W7)
            state["balance_after"] = {"lamports": _int(self.rpc.get_balance(self.wallet.pubkey()), "getBalance"),
                                      "at": now}
        except _RPC_ERRORS:
            state["balance_after"] = None
        with self.ledger.transaction():
            self.ledger.append_receipt("withdraw", {"mode": "live", "from": pending.get("from"),
                                                    "to": pending.get("to"), "lamports": lamports,
                                                    "fee_lamports": pending.get("fee_lamports"),
                                                    "signature": pending.get("signature"),
                                                    **({"late": True} if late else {})}, ts=now)
            _count_withdrawn(self.ledger, lamports, now)
            if self.settings.withdraw_to and pending.get("to") == self.settings.withdraw_to:
                self._set(state, now, "done")
            else:
                self._save(state, now)
        log.warning("withdraw_done to=%s sol=%.9f signature=%s", pending.get("to"), lamports / LAMPORTS_PER_SOL,
                    pending.get("signature"))

    # ------------------------------------------------------------------ state
    def _clear_hold(self, now: float) -> None:
        if live_hold(self.ledger) is None:
            return
        with self.ledger.transaction():
            self.ledger.set_kv(KV_HOLD, None)
            self.ledger.append_receipt("note", {"event": "withdraw_hold_cleared", "mode": "paper"}, ts=now)
        log.info("withdraw_hold_cleared: the bot ran in paper mode after a live withdrawal")

    def _fresh(self, previous: dict[str, Any], now: float) -> dict[str, Any]:
        return {"to": self.settings.withdraw_to, "mode": self.settings.trading_mode, "since": now, "status": None,
                "error": None, "updated_at": now, "open_positions": 0, "pending_swaps": 0, "drift": 0,
                "dest_ok": None, "dest_ok_at": None, "preview": None, "pending": None,
                "closing": previous.get("closing"),
                "unclosable": [], "close_failures": 0, "expired": previous.get("expired") or [], "failures": 0,
                "retry_at": None, "next_check_at": None, "sent_lamports": 0, "left_lamports": None,
                "reserve_lamports": 0, "balance_after": previous.get("balance_after"), "paper": None, "noted": None,
                "last": previous.get("last")}

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


def _coins(n: int) -> str:
    return f"{n} coin{'' if n == 1 else 's'}"


def _minutes(seconds: float) -> str:
    return f"about {max(1, round(seconds / 60))} min"


def _live_needs(settings: Settings) -> str:
    """What a paper-mode owner must set for a real withdrawal (live mode refuses to start without each)."""
    token = ("you already have a strong one" if settings.dashboard_token
             and dashboard_token_problem(settings.dashboard_token.reveal()) is None
             else "a password of at least 24 random characters; live mode does not start without it")
    return (f"To really send it, set in Railway: TRADING_MODE=live, LIVE_CONFIRM={LIVE_CONFIRM_PHRASE} and "
            f"DASHBOARD_TOKEN ({token}). The bot still buys nothing while WITHDRAW_TO is set.")


def page_view(settings: Settings, state: dict[str, Any] | None, now: float,
              hold: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """The withdrawal as the page shows it - ``{"status", "to", "level": "bad"|"warn", "text"}`` - or None when
    WITHDRAW_TO is not set and no hold applies. ``bad`` (red) while it is under way, ``warn`` once there is a
    result. The destination is always shown in FULL (a look-alike matches the first and last characters).
    ``hold``: :func:`live_hold` (live, WITHDRAW_TO deleted: the bot buys nothing until it ran in paper)."""
    target = settings.withdraw_to
    if not target:
        if hold is not None and settings.is_live:
            return {"status": "hold", "to": str(hold.get("to") or ""), "level": "bad",
                    "text": "After the withdrawal the bot buys nothing with real money. Next, in Railway: delete "
                            "LIVE_CONFIRM, set TRADING_MODE=paper and Deploy. Going live again later is the normal "
                            "checklist."}
        return None
    if not state or state.get("to") != target or state.get("mode") != settings.trading_mode \
            or state.get("status") in (None, "off"):
        return {"status": "starting", "to": target, "level": "bad",
                "text": f"Withdrawing everything to {target}: starting. The bot buys nothing while WITHDRAW_TO is set."}
    status, error = str(state.get("status")), state.get("error") or ""
    open_n = int(state.get("open_positions") or 0) + int(state.get("drift") or 0)
    pending = state.get("pending") if isinstance(state.get("pending"), dict) else None
    reserve = int(state.get("reserve_lamports") or 0)
    stay = (f" {_coins(open_n)} could not be sold yet and stay in the bot wallet"
            + (f", with {_sol(reserve)} SOL kept to sell them; the rest follows once they are sold." if reserve
               else ".")) if open_n else ""
    retry = state.get("retry_at")
    wait = f" Trying again in {_minutes(retry - now)}." \
        if isinstance(retry, (int, float)) and retry > now else " Trying again soon."
    after = (" Next, in Railway: delete WITHDRAW_TO and LIVE_CONFIRM, set TRADING_MODE=paper, Deploy."
             if settings.is_live else " The bot buys nothing while WITHDRAW_TO is set: delete it in Railway to "
                                      "trade (paper) again.")
    cancel = "Wrong address? Delete WITHDRAW_TO in Railway and Deploy: nothing has been sent."
    if status == "selling":
        doing = f"selling {_coins(open_n)} first" if open_n else "waiting for a trade to settle first"
        text, level = f"Withdrawing everything to {target}: {doing}, buying nothing. {cancel}", "bad"
    elif status == "arming":
        armed = state.get("dest_ok_at")
        left = float(armed) + ARM_S - now if isinstance(armed, (int, float)) else ARM_S
        found_preview = state.get("preview")
        preview: dict[str, Any] = found_preview if isinstance(found_preview, dict) else {}
        amount = f" (about {_sol(preview.get('balance_lamports'))} SOL)" if preview else ""
        text, level = (f"In {_minutes(left)} the bot sends ALL its SOL{amount} to {target}. Check every character "
                       f"against Phantom (Receive, Solana). Delete WITHDRAW_TO in Railway and Deploy before then to "
                       "cancel."), "bad"
    elif status == "closing":
        found_closing = state.get("closing")
        closing: dict[str, Any] = found_closing if isinstance(found_closing, dict) else {}
        text, level = (f"Withdrawing everything to {target}: first closing {len(closing.get('accounts') or [])} empty "
                       f"coin accounts (they give back {_sol(closing.get('reclaim_lamports'))} SOL)."), "bad"
    elif status == "sending" and pending:
        text, level = (f"Withdrawing: sent {_sol(pending.get('lamports'))} SOL to {target}, waiting for the network "
                       "to confirm."), "bad"
    elif status == "done":
        text, level = (f"Withdrawal done: {_sol(state.get('sent_lamports'))} SOL went to {target} (check Phantom)."
                       + stay + after), "warn"
    elif status == "empty":
        text, level = (f"Nothing to withdraw: the bot wallet has no SOL left to send to {target}." + stay + after,
                       "warn")
    elif status == "blocked":
        text, level = f"Can't withdraw to {target}: {error}", "bad"
    elif status == "error":
        text, level = f"Withdrawing to {target}: the last try did not work ({error}).{wait}", "bad"
    elif status == "no_wallet":
        text, level = "WITHDRAW_TO is set, but there is no bot wallet: nothing to send." + after, "warn"
    elif status == "paper":
        found = state.get("paper")
        paper: dict[str, Any] = found if isinstance(found, dict) else {}
        closes = int(paper.get("close_accounts") or 0)
        extra = (f" It would first close {closes} empty coin accounts (+{_sol(paper.get('reclaim_lamports'))} SOL)."
                 if closes else "")
        if paper.get("would_send_lamports"):
            text = (f"Practice mode: the bot would send {_sol(paper.get('would_send_lamports'))} SOL to {target} "
                    f"(network fee {_sol(paper.get('fee_lamports'))} SOL).{extra} Nothing was sent. "
                    + _live_needs(settings))
        else:
            text = (f"Practice mode: nothing to send to {target}: the bot wallet holds "
                    f"{_sol(paper.get('balance_lamports'))} SOL, too little to move after the network fee. The bot "
                    "buys nothing while WITHDRAW_TO is set.")
        level = "warn"
    else:
        text, level = f"Withdrawing everything to {target}: working on it.", "bad"
    return {"status": status, "to": target, "level": level, "text": text}


def last_withdrawal(state: dict[str, Any] | None) -> dict[str, Any] | None:
    """The last CONFIRMED real withdrawal ``{"sol", "to", "at", "signature"}`` (kept after WITHDRAW_TO is gone)."""
    last = state.get("last") if isinstance(state, dict) else None
    if not isinstance(last, dict) or not isinstance(last.get("lamports"), int):
        return None
    return {"sol": last["lamports"] / LAMPORTS_PER_SOL, "to": str(last.get("to") or ""), "at": last.get("at"),
            "signature": str(last.get("signature") or "")}


def fresh_balance(state: dict[str, Any] | None, after: float | None) -> tuple[float, float] | None:
    """``(SOL, read at)`` of the bot wallet read right after a transfer landed, when that is newer than
    ``after`` (the latest equity point), else None."""
    reading = state.get("balance_after") if isinstance(state, dict) else None
    if not isinstance(reading, dict) or not isinstance(reading.get("lamports"), int):
        return None
    at = reading.get("at")
    if not isinstance(at, (int, float)) or (after is not None and at <= after):
        return None
    return reading["lamports"] / LAMPORTS_PER_SOL, float(at)
