"""WITHDRAW_TO (nightcrawler.withdraw): buy nothing, sell everything, then ONE SystemProgram transfer of ALL the
SOL minus the exact network fee, signed by the keystore, simulated, confirmed and receipted - exactly once across
restarts. Paper mode only shows what it would send. Every transaction here goes to :class:`FakeChain`, a tiny
in-memory Solana that applies the runtime's fee and rent rules; nothing is ever sent anywhere."""

from __future__ import annotations

import base64
import itertools
import struct
from pathlib import Path
from typing import Any, Callable, Iterator

import pytest

pytest.importorskip("solders")

from solders.keypair import Keypair  # noqa: E402
from solders.pubkey import Pubkey  # noqa: E402
from solders.transaction import Transaction  # noqa: E402

from fakes import FakeClock, FakeHttp  # noqa: E402
from nightcrawler import withdraw as withdraw_mod  # noqa: E402
from nightcrawler.base58 import b58encode  # noqa: E402
from nightcrawler.broker import keystore  # noqa: E402
from nightcrawler.broker.paper import PaperBroker  # noqa: E402
from nightcrawler.cocoon import Cocoon  # noqa: E402
from nightcrawler.config import LIVE_CONFIRM_PHRASE, Settings  # noqa: E402
from nightcrawler.crawler import Crawler  # noqa: E402
from nightcrawler.engine import Engine, build_app  # noqa: E402
from nightcrawler.http import HttpClient  # noqa: E402
from nightcrawler.judge import Judge  # noqa: E402
from nightcrawler.ledger import Ledger  # noqa: E402
from nightcrawler.pagestate import FUND_HELP, build_page_state  # noqa: E402
from nightcrawler.radar import Radar  # noqa: E402
from nightcrawler.risk import RiskManager  # noqa: E402
from nightcrawler.sources import build_sources  # noqa: E402
from nightcrawler.sources.solana_rpc import RpcError  # noqa: E402
from nightcrawler.withdraw import (  # noqa: E402
    ARM_S,
    BASE_FEE_LAMPORTS,
    KV_STATE,
    MIN_FUNDING_LAMPORTS,
    PAPER_RECHECK_S,
    REBROADCAST_S,
    RECHECK_S,
    RENT_EXEMPT_MIN_LAMPORTS,
    RETRY_S,
    SELL_WAIT_S,
    TOKEN_2022_PROGRAM,
    TOKEN_PROGRAM,
    Withdrawer,
    account_problem,
    destination_problem,
    page_view,
    reserve_lamports,
    withdrawable_lamports,
)
from test_engine import Rig  # noqa: E402
from world import World, make_world  # noqa: E402

NOW = 1_791_475_200.0
SOL = 1_000_000_000
STRONG_TOKEN = "withdraw-dashboard-passw0rd-8d2f6a1c9e"
OWNER = str(Keypair.from_seed(bytes([7]) * 32).pubkey())  # an on-curve wallet address (the owner's Phantom)
SYSTEM = "11111111111111111111111111111111"
PLAIN_WALLET = {"owner": SYSTEM, "executable": False, "data": ["", "base64"], "lamports": 5 * SOL}
JARGON_WORDS = ("lamport", "mint", "slippage", "ledger", " kv", "bps")


# --------------------------------------------------------------------------- a tiny Solana


class FakeChain:
    """Balances, one blockhash at a time, a signature table and the runtime's fee and rent rules for a fee payer
    that drains itself. Records every call; ``land()`` applies a posted transfer the way the runtime would.

    ``funder`` (default the owner's wallet) exists on chain and funded every starting balance with a plain SOL
    transfer that both addresses' histories show; ``token_accounts`` are the bot's token accounts
    (``getTokenAccountsByOwner``); ``hidden`` signatures are unknown to a lagging node."""

    def __init__(self, balances: dict[str, int], *, fee: int = BASE_FEE_LAMPORTS,
                 rent_min: int = RENT_EXEMPT_MIN_LAMPORTS, funder: str | None = OWNER) -> None:
        self.balances = dict(balances)
        self.fee, self.rent_min = fee, rent_min
        self.calls: list[str] = []
        self.sent: list[str] = []
        self.simulated: list[str] = []
        self.statuses: dict[str, dict[str, Any]] = {}
        self.accounts: dict[str, Any] = {}
        self.height = 1_000  # finalized block height
        self.counter = itertools.count(1)
        self.new_blockhash()
        self.fail: set[str] = set()
        self.sim_err: Any = None
        self.on_send: Callable[[str], None] | None = None
        self.auto_land = False
        self.history: dict[str, list[str]] = {}  # newest first
        self.parsed: dict[str, dict[str, Any]] = {}
        self.token_accounts: dict[str, dict[str, Any]] = {}
        self.hidden: set[str] = set()
        self.sim_err_for: Callable[[str], Any] | None = None
        if funder is not None:
            self.accounts[funder] = dict(PLAIN_WALLET)
            for address, lamports in sorted(balances.items()):
                if lamports > 0:
                    self.fund(funder, address, lamports, move=False)

    def fund(self, source: str, dest: str, lamports: int, *, move: bool = True) -> str:
        """A plain SOL transfer ``source`` -> ``dest`` (as Phantom's Send makes it), in both histories."""
        signature = b58encode(next(self.counter).to_bytes(8, "big") * 8)
        for address in (source, dest):
            self.history.setdefault(address, []).insert(0, signature)
        self.parsed[signature] = {"slot": 7, "meta": {"err": None, "innerInstructions": []}, "transaction": {
            "message": {"instructions": [
                {"program": "compute-budget", "programId": "ComputeBudget111111111111111111111111111111",
                 "parsed": {"type": "setComputeUnitLimit", "info": {"computeUnitLimit": 500}}},
                {"program": "system", "programId": SYSTEM,
                 "parsed": {"type": "transfer", "info": {"source": source, "destination": dest,
                                                          "lamports": lamports}}}]}}}
        if move:
            self.balances[source] = self.balances.get(source, 0) - lamports
            self.balances[dest] = self.balances.get(dest, 0) + lamports
        return signature

    def token_account(self, owner: str, *, mint: str, amount: int = 0, lamports: int = 2_039_280,
                      program: str = TOKEN_PROGRAM, state: str = "initialized") -> str:
        address = str(Keypair().pubkey())
        self.token_accounts[address] = {"owner": owner, "mint": mint, "amount": amount, "lamports": lamports,
                                        "program": program, "state": state}
        return address

    def new_blockhash(self) -> None:
        self.blockhash = b58encode(bytes([next(self.counter)]) * 32)
        self.last_valid = self.height + 150

    def _raise(self, method: str) -> None:
        self.calls.append(method)
        if method in self.fail:
            raise RpcError(-32000, "node is behind", method)

    def call(self, method: str, params: list[Any]) -> Any:
        self._raise(method)
        ctx = {"context": {"slot": 1}}
        if method == "getSignaturesForAddress":
            opts = params[1] if len(params) > 1 else {}
            sigs = self.history.get(params[0], [])
            if opts.get("before") in sigs:
                sigs = sigs[sigs.index(opts["before"]) + 1:]
            return [{"signature": sig, "err": None, "slot": 7} for sig in sigs[:opts.get("limit", 1000)]]
        if method == "getTransaction":
            signature = params[0]
            if signature in self.hidden:
                return None
            if signature in self.parsed:
                return self.parsed[signature]
            status = self.statuses.get(signature)
            return None if status is None else {"slot": status["slot"], "meta": {"err": status["err"]}}
        if method == "getTokenAccountsByOwner":
            program = params[1]["programId"]
            return {**ctx, "value": [
                {"pubkey": address, "account": {"lamports": a["lamports"], "owner": a["program"], "executable": False,
                                                "data": {"program": "spl-token", "parsed": {"type": "account", "info": {
                                                    "mint": a["mint"], "owner": a["owner"], "state": a["state"],
                                                    "isNative": False,
                                                    "tokenAmount": {"amount": str(a["amount"]), "decimals": 6}}}}}}
                for address, a in self.token_accounts.items() if a["owner"] == params[0] and a["program"] == program]}
        if method == "getLatestBlockhash":
            return {**ctx, "value": {"blockhash": self.blockhash, "lastValidBlockHeight": self.last_valid}}
        if method == "getFeeForMessage":
            return {**ctx, "value": self.fee}
        if method == "getMinimumBalanceForRentExemption":
            return self.rent_min
        if method == "getBlockHeight":
            return self.height
        if method == "getAccountInfo":
            info = self.accounts.get(params[0])
            if info is None and self.balances.get(params[0], 0) > 0:
                info = {**PLAIN_WALLET, "lamports": self.balances[params[0]]}
            return {**ctx, "value": info}
        if method == "sendTransaction":
            tx_b64 = params[0]
            if self.on_send is not None:
                self.on_send(tx_b64)
            self.sent.append(tx_b64)
            if self.auto_land:
                self.land(tx_b64)
            return str(Transaction.from_bytes(base64.b64decode(tx_b64)).signatures[0])
        raise AssertionError(f"unexpected RPC method {method}")

    def get_balance(self, address: str) -> int:
        self._raise("getBalance")
        return self.balances.get(address, 0)

    def simulate(self, tx_b64: str) -> dict[str, Any]:
        self._raise("simulateTransaction")
        self.simulated.append(tx_b64)
        err = self.sim_err_for(tx_b64) if self.sim_err_for is not None else self.sim_err
        return {"err": err, "logs": [], "units_consumed": 150}

    def signature_status(self, signature: str) -> dict[str, Any] | None:
        self._raise("getSignatureStatuses")
        return None if signature in self.hidden else self.statuses.get(signature)

    def land(self, tx_b64: str) -> None:
        """Apply the transfer like the runtime: fee first (the payer must stay rent-exempt or reach 0), then the
        transfer (the payer ends at 0 or rent-exempt; a new destination must become rent-exempt). A transaction
        of CloseAccount instructions returns each (empty) account's lamports to its destination."""
        if decode_any(tx_b64)["kind"] == "close":
            self.land_close(tx_b64)
            return
        tx = decode(tx_b64)
        source, to, lamports = tx["from"], tx["to"], tx["lamports"]
        after_fee = self.balances.get(source, 0) - self.fee
        assert after_fee == 0 or after_fee >= self.rent_min, "InsufficientFundsForRent (fee payer)"
        left = after_fee - lamports
        assert left >= 0, "insufficient funds"
        assert left == 0 or left >= self.rent_min, "InsufficientFundsForRent (source)"
        assert self.balances.get(to, 0) + lamports >= self.rent_min, "InsufficientFundsForRent (destination)"
        self.balances[source] = left
        self.balances[to] = self.balances.get(to, 0) + lamports
        self.statuses[tx["signature"]] = {"slot": 9, "confirmations": None, "err": None,
                                          "confirmation_status": "confirmed"}

    def land_close(self, tx_b64: str) -> None:
        tx = decode_any(tx_b64)
        payer = tx["payer"]
        assert self.balances.get(payer, 0) >= self.fee
        self.balances[payer] -= self.fee
        for account, dest, owner, program in tx["closes"]:
            held = self.token_accounts.pop(account)
            assert held["amount"] == 0 and held["owner"] == owner == payer and held["program"] == program
            self.balances[dest] = self.balances.get(dest, 0) + held["lamports"]
        self.statuses[tx["signature"]] = {"slot": 9, "confirmations": None, "err": None,
                                          "confirmation_status": "confirmed"}


def decode_any(tx_b64: str) -> dict[str, Any]:
    """Either one SystemProgram transfer (``kind`` transfer) or only CloseAccount instructions of the two token
    programs (``kind`` close: ``closes`` = [(account, destination, owner, program)]); verified signature."""
    tx = Transaction.from_bytes(base64.b64decode(tx_b64))
    tx.verify()
    message = tx.message
    keys = [str(k) for k in message.account_keys]
    programs = {keys[ix.program_id_index] for ix in message.instructions}
    if programs == {SYSTEM}:
        return {"kind": "transfer", **decode(tx_b64)}
    assert programs <= {TOKEN_PROGRAM, TOKEN_2022_PROGRAM}, programs
    assert message.header.num_required_signatures == 1
    closes = []
    for ix in message.instructions:
        assert bytes(ix.data) == bytes([9])  # TokenInstruction::CloseAccount
        account, dest, owner = (keys[i] for i in ix.accounts)
        closes.append((account, dest, owner, keys[ix.program_id_index]))
    return {"kind": "close", "payer": keys[0], "closes": closes, "signature": str(tx.signatures[0])}


def decode(tx_b64: str) -> dict[str, Any]:
    """A posted transaction, checked: legacy, ONE SystemProgram transfer, the fee payer signs, signature valid."""
    tx = Transaction.from_bytes(base64.b64decode(tx_b64))
    tx.verify()  # raises on a bad signature
    message = tx.message
    keys = [str(k) for k in message.account_keys]
    assert message.header.num_required_signatures == 1 and len(message.instructions) == 1
    ix = message.instructions[0]
    assert keys[ix.program_id_index] == SYSTEM
    kind, lamports = struct.unpack("<IQ", bytes(ix.data))
    assert kind == 2  # SystemInstruction::Transfer
    source, to = keys[ix.accounts[0]], keys[ix.accounts[1]]
    assert source == keys[0]  # the bot wallet pays its own fee
    return {"from": source, "to": to, "lamports": lamports, "signature": str(tx.signatures[0]),
            "blockhash": str(message.recent_blockhash)}


# --------------------------------------------------------------------------- fixtures


@pytest.fixture
def ledger(tmp_path: Path, fake_clock: FakeClock) -> Iterator[Ledger]:
    with Ledger(tmp_path / "nc.db", clock=fake_clock) as led:
        yield led


@pytest.fixture
def wallet(tmp_path: Path) -> Any:
    return keystore.create(tmp_path / "keys")


def live(make_settings: Callable[..., Settings], **extra: Any) -> Settings:
    return make_settings(TRADING_MODE="live", LIVE_CONFIRM=LIVE_CONFIRM_PHRASE, BOT_WALLET_MODE="generated",
                         DASHBOARD_TOKEN=STRONG_TOKEN, **{"WITHDRAW_TO": OWNER, **extra})


def arm(w: Withdrawer, now: float = NOW, **counts: Any) -> str:
    """WITHDRAW_TO set ARM_S ago (the owner had 10 minutes to cancel): the step at ``now``."""
    assert w.run(now - ARM_S, **counts) in ("arming", "selling")
    return w.run(now, **counts)


def receipts(ledger: Ledger, kind: str, event: str | None = None) -> list[dict[str, Any]]:
    return [r.payload for r in ledger.receipts()
            if r.kind == kind and (event is None or r.payload.get("event") == event)]


def state(ledger: Ledger) -> dict[str, Any]:
    return ledger.get_kv(KV_STATE)


# --------------------------------------------------------------------------- the amount


def test_the_amount_is_everything_minus_the_fee_and_never_strands_a_lamport() -> None:
    fee, rent = 5000, 890_880
    assert withdrawable_lamports(SOL, fee, rent) == SOL - fee
    assert withdrawable_lamports(rent + fee, fee, rent) == rent  # exactly the rent-exempt minimum: allowed
    assert withdrawable_lamports(rent + fee - 1, fee, rent) == 0  # the payer would be left rent-paying
    for balance in (0, 1, fee - 1, fee, fee + 1):
        assert withdrawable_lamports(balance, fee, rent) == 0
    for balance in range(rent + fee, rent + fee + 50_000, 997):  # whenever it sends, the wallet ends at exactly 0
        assert withdrawable_lamports(balance, fee, rent) + fee == balance
    for bad in (-1, 1.5, True, "1"):
        with pytest.raises(ValueError):
            withdrawable_lamports(bad, fee, rent)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- the destination


def test_destination_rules(wallet: Any) -> None:
    own = wallet.pubkey()
    pda, _ = Pubkey.find_program_address([b"token-account"], Pubkey.from_string(TOKEN_PROGRAM))
    assert destination_problem(OWNER, own) is None
    assert "bot's own address" in destination_problem(own, own)
    assert "not a Solana address" in destination_problem("not-an-address", own)
    for unspendable in (SYSTEM, "1nc1nerator11111111111111111111111111111111"):
        assert destination_problem(unspendable, own)
    assert "not a wallet address" in destination_problem(str(pda), own)  # off the curve: a token account
    assert "does not exist" in account_problem(None)  # nobody ever used it: a typo, not the owner's wallet
    assert account_problem({"owner": SYSTEM, "executable": False, "data": ["", "base64"], "lamports": 5}) is None
    for bad in ({"owner": TOKEN_PROGRAM, "executable": False, "data": ["AAAA", "base64"]},
                {"owner": "BPFLoaderUpgradeab1e11111111111111111111111", "executable": True, "data": ["", "base64"]},
                {"owner": SYSTEM, "executable": False, "data": ["AAAA", "base64"]}, "junk"):
        assert account_problem(bad), bad


# --------------------------------------------------------------------------- live: exactly once


def test_live_sends_all_the_sol_once_confirms_and_receipts_it(make_settings: Callable[..., Settings], ledger: Ledger,
                                                              wallet: Any, fake_clock: FakeClock) -> None:
    bot = wallet.pubkey()
    chain = FakeChain({bot: 431_250_000})
    seen_before_send: list[Any] = []
    chain.on_send = lambda tx: seen_before_send.append((state(ledger)["pending"]["signature"],
                                                        receipts(ledger, "note", "withdraw_sending")))
    w = Withdrawer(live(make_settings), ledger, chain, wallet, fake_clock)
    assert arm(w) == "sending"
    [tx_b64] = chain.sent
    tx = decode(tx_b64)
    assert tx == {"from": bot, "to": OWNER, "lamports": 431_250_000 - 5000, "signature": tx["signature"],
                  "blockhash": chain.blockhash}
    assert chain.simulated == [tx_b64]  # simulated before it was sent
    # write-ahead: the pending transfer and its note were saved BEFORE the transaction left
    [(pending_signature, notes)] = seen_before_send
    assert pending_signature == tx["signature"] and notes[0]["signature"] == tx["signature"]
    assert receipts(ledger, "withdraw") == []

    chain.land(tx_b64)
    assert w.run(NOW + 5) == "done"
    [receipt] = receipts(ledger, "withdraw")
    assert receipt == {"mode": "live", "from": bot, "to": OWNER, "lamports": 431_245_000, "fee_lamports": 5000,
                       "signature": tx["signature"]}
    assert chain.balances[bot] == 0 and chain.balances[OWNER] == 431_245_000  # nothing stranded
    saved = state(ledger)
    assert saved["pending"] is None and saved["sent_lamports"] == saved["last"]["lamports"] == 431_245_000
    for later in (NOW + 6, NOW + 10 + RECHECK_S, NOW + 20 + 2 * RECHECK_S):
        assert w.run(later) == "done"
    assert len(chain.sent) == 1 and len(receipts(ledger, "withdraw")) == 1
    assert withdraw_mod.withdrawn_lamports(ledger, NOW + 5, NOW - 60) == (431_245_000, 431_245_000)
    assert withdraw_mod.withdrawn_lamports(ledger, NOW + 86_400, NOW + 86_000) == (431_245_000, 0)  # a later day
    assert withdraw_mod.withdrawn_lamports(ledger, NOW - 1, NOW - 60) == (0, 0)  # not landed yet at that point


def test_a_restart_never_sends_a_second_transfer(make_settings: Callable[..., Settings], ledger: Ledger, wallet: Any,
                                                 fake_clock: FakeClock) -> None:
    bot = wallet.pubkey()
    chain = FakeChain({bot: 2 * SOL})
    settings = live(make_settings)
    chain.fail.add("sendTransaction")  # the first post dies on the way (or the process dies right after)
    assert arm(Withdrawer(settings, ledger, chain, wallet, fake_clock)) == "sending"
    pending = state(ledger)["pending"]
    chain.fail.clear()

    restarted = Withdrawer(settings, ledger, chain, wallet, fake_clock)  # a new process, same ledger
    assert restarted.run(NOW + 5) == "sending" and chain.sent == []  # too soon to re-post
    restarted.run(NOW + 5 + REBROADCAST_S)
    restarted.run(NOW + 5 + 2 * REBROADCAST_S)
    assert chain.sent == [pending["tx_b64"], pending["tx_b64"]]  # only the IDENTICAL transaction, re-posted
    assert {decode(t)["signature"] for t in chain.sent} == {pending["signature"]}
    assert chain.simulated == [pending["tx_b64"]]  # nothing new was even built

    chain.land(chain.sent[-1])
    assert restarted.run(NOW + 100) == "done"
    assert len(receipts(ledger, "withdraw")) == 1 and chain.balances[bot] == 0


def test_only_a_dead_transfer_is_ever_replaced(make_settings: Callable[..., Settings], ledger: Ledger, wallet: Any,
                                               fake_clock: FakeClock) -> None:
    bot = wallet.pubkey()
    chain = FakeChain({bot: SOL})
    w = Withdrawer(live(make_settings), ledger, chain, wallet, fake_clock)
    arm(w)
    first = state(ledger)["pending"]
    chain.statuses[first["signature"]] = {"slot": 5, "confirmations": 0, "err": None,
                                          "confirmation_status": "processed"}
    chain.height = first["last_valid_block_height"] + 10
    assert w.run(NOW + 60) == "sending"  # seen in a block, not final: wait, even past its blockhash
    assert state(ledger)["pending"]["signature"] == first["signature"]
    del chain.statuses[first["signature"]]  # that block was dropped: the chain never kept it ...
    chain.height = first["last_valid_block_height"]
    w.run(NOW + 120)
    assert state(ledger)["pending"]["signature"] == first["signature"]  # ... but its blockhash is still valid
    chain.height = first["last_valid_block_height"] + 1  # now dead at the FINALIZED height: it can never land
    chain.new_blockhash()  # (the network has moved on)
    assert w.run(NOW + 180) == "sending"  # so it is replaced, from the balance read right now
    assert receipts(ledger, "note", "withdraw_expired")[0]["signature"] == first["signature"]
    second = state(ledger)["pending"]
    assert second["signature"] != first["signature"] and decode(second["tx_b64"])["blockhash"] == chain.blockhash
    chain.land(second["tx_b64"])
    with pytest.raises(AssertionError, match="insufficient|Rent"):
        chain.land(first["tx_b64"])  # even the dead one could never pay twice: the money is there only once
    assert w.run(NOW + 182) == "done" and chain.balances[bot] == 0


def test_a_transfer_the_network_refused_is_retried_later_with_backoff(make_settings: Callable[..., Settings],
                                                                      ledger: Ledger, wallet: Any,
                                                                      fake_clock: FakeClock) -> None:
    bot = wallet.pubkey()
    chain = FakeChain({bot: SOL})
    w = Withdrawer(live(make_settings), ledger, chain, wallet, fake_clock)
    arm(w)
    first = state(ledger)["pending"]
    chain.statuses[first["signature"]] = {"slot": 5, "confirmations": None, "err": {"InstructionError": [0, "X"]},
                                          "confirmation_status": "finalized"}
    chain.balances[bot] -= chain.fee  # a failed transaction still pays its fee
    assert w.run(NOW + 30) == "error"
    assert receipts(ledger, "note", "withdraw_failed")[0]["stage"] == "chain"
    assert state(ledger)["retry_at"] == NOW + 30 + RETRY_S
    assert w.run(NOW + 31) == "error" and len(chain.sent) == 1  # waits
    assert w.run(NOW + 30 + RETRY_S) == "sending"
    second = state(ledger)["pending"]
    assert decode(second["tx_b64"])["lamports"] == SOL - 2 * chain.fee  # from the balance read right before signing
    chain.statuses[second["signature"]] = {**chain.statuses[first["signature"]]}
    w.run(NOW + 40 + RETRY_S)
    assert state(ledger)["retry_at"] == NOW + 40 + RETRY_S + 2 * RETRY_S  # doubles per failure that cost a fee


def test_nothing_is_sent_unchecked(make_settings: Callable[..., Settings], ledger: Ledger, wallet: Any,
                                   fake_clock: FakeClock) -> None:
    bot = wallet.pubkey()
    chain = FakeChain({bot: SOL})
    w = Withdrawer(live(make_settings), ledger, chain, wallet, fake_clock)
    chain.sim_err = {"InstructionError": [0, {"Custom": 1}]}
    assert arm(w) == "error" and chain.sent == []
    assert receipts(ledger, "note", "withdraw_failed")[0]["stage"] == "simulate"
    chain.sim_err = None
    for method in ("simulateTransaction", "getFeeForMessage", "getLatestBlockhash", "getBalance", "getAccountInfo",
                   "getMinimumBalanceForRentExemption"):
        chain.fail = {method}
        assert w.run(NOW + 10_000) == "error", method
        assert chain.sent == [], method
        ledger.set_kv(KV_STATE, {**state(ledger), "retry_at": None})
    chain.fail = set()
    assert w.run(NOW + 20_000) == "sending" and len(chain.sent) == 1


def test_dust_that_the_network_cannot_move_is_left_and_said(make_settings: Callable[..., Settings], ledger: Ledger,
                                                            wallet: Any, fake_clock: FakeClock) -> None:
    bot = wallet.pubkey()
    chain = FakeChain({bot: RENT_EXEMPT_MIN_LAMPORTS + BASE_FEE_LAMPORTS - 1})
    chain.fund(OWNER, bot, SOL, move=False)  # funded with more, then traded down to dust
    w = Withdrawer(live(make_settings), ledger, chain, wallet, fake_clock)
    assert arm(w) == "empty" and chain.sent == []
    assert state(ledger)["left_lamports"] == RENT_EXEMPT_MIN_LAMPORTS + BASE_FEE_LAMPORTS - 1


def test_a_wrong_destination_blocks_the_transfer(make_settings: Callable[..., Settings], ledger: Ledger,
                                                 wallet: Any, fake_clock: FakeClock) -> None:
    bot = wallet.pubkey()
    chain = FakeChain({bot: SOL})
    chain.accounts[OWNER] = {"owner": TOKEN_PROGRAM, "executable": False, "data": ["AAAA", "base64"]}
    assert Withdrawer(live(make_settings), ledger, chain, wallet, fake_clock).run(NOW) == "blocked"
    assert chain.sent == [] and "token account" in state(ledger)["error"]
    own = Withdrawer(live(make_settings, WITHDRAW_TO=bot), ledger, chain, wallet, fake_clock)
    assert own.run(NOW + 1) == "blocked" and "own address" in state(ledger)["error"] and chain.sent == []


def test_coins_are_sold_first_but_cannot_hold_the_sol_hostage(make_settings: Callable[..., Settings],
                                                              ledger: Ledger, wallet: Any,
                                                              fake_clock: FakeClock) -> None:
    bot = wallet.pubkey()
    chain = FakeChain({bot: SOL})
    w = Withdrawer(live(make_settings), ledger, chain, wallet, fake_clock)
    assert w.run(NOW, open_positions=2) == "selling"
    assert not {"getBalance", "sendTransaction"} & set(chain.calls)  # only the destination was checked
    assert w.run(NOW + 60, open_positions=0, pending_swaps=1) == "selling"
    assert w.run(NOW + 70, drift=1) == "selling"  # a coin the wallet holds but the books do not: also waited for
    assert w.run(NOW + SELL_WAIT_S, open_positions=1) == "sending"  # a coin nobody buys: the SOL goes anyway ...
    [tx] = [decode(t) for t in chain.sent]
    keep = reserve_lamports(1)  # ... all but what selling that coin still needs
    assert keep >= 2 * 2_000_000 + 2_039_280 and tx["lamports"] == SOL - BASE_FEE_LAMPORTS - keep
    chain.land(chain.sent[0])
    assert chain.balances[bot] == keep
    w.run(NOW + SELL_WAIT_S + 5, open_positions=1)
    view = page_view(live(make_settings), state(ledger), NOW + SELL_WAIT_S + 6)
    assert view is not None and view["status"] == "done" and "1 coin could not be sold" in view["text"]
    assert w.run(NOW + SELL_WAIT_S + 10 + RECHECK_S, open_positions=1) == "done" and len(chain.sent) == 1
    chain.balances[bot] += 50_000_000  # the coin finally sold
    assert w.run(NOW + SELL_WAIT_S + 20 + 2 * RECHECK_S, open_positions=0) == "sending"  # now the rest goes
    chain.land(chain.sent[-1])
    assert chain.balances[bot] == 0


def test_a_transfer_in_flight_is_followed_up_after_withdraw_to_is_deleted(make_settings: Callable[..., Settings],
                                                                          ledger: Ledger, wallet: Any,
                                                                          fake_clock: FakeClock) -> None:
    bot = wallet.pubkey()
    chain = FakeChain({bot: SOL})
    arm(Withdrawer(live(make_settings), ledger, chain, wallet, fake_clock))
    chain.land(chain.sent[0])
    gone = make_settings(TRADING_MODE="live", LIVE_CONFIRM=LIVE_CONFIRM_PHRASE, BOT_WALLET_MODE="generated",
                         DASHBOARD_TOKEN=STRONG_TOKEN)  # WITHDRAW_TO deleted while the transfer was in flight
    assert withdraw_mod.has_pending(ledger)
    assert Withdrawer(gone, ledger, chain, wallet, fake_clock).run(NOW + 5) == "off"
    assert len(receipts(ledger, "withdraw")) == 1 and not withdraw_mod.has_pending(ledger)
    assert page_view(gone, state(ledger), NOW + 6) is None


# --------------------------------------------------------------------------- paper: show, never sign, never send


def test_paper_mode_only_simulates(make_settings: Callable[..., Settings], ledger: Ledger, wallet: Any,
                                   fake_clock: FakeClock, monkeypatch: pytest.MonkeyPatch) -> None:
    def never(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("paper mode signed a transfer")

    monkeypatch.setattr(withdraw_mod, "sign_transfer", never)
    monkeypatch.setattr(keystore, "sign_transfer", never)
    bot = wallet.pubkey()
    chain = FakeChain({bot: 250_000_000})
    settings = make_settings(BOT_WALLET_MODE="generated", WITHDRAW_TO=OWNER)
    w = Withdrawer(settings, ledger, chain, wallet, fake_clock)
    assert w.run(NOW, open_positions=1) == "selling"  # paper positions are (pretend-)sold first
    assert w.run(NOW + 10) == "paper"
    saved = state(ledger)
    assert saved["paper"]["would_send_lamports"] == 250_000_000 - 5000 and saved["paper"]["fee_exact"] is True
    assert saved["pending"] is None and "tx_b64" not in str(saved)
    assert chain.sent == [] and chain.simulated == [] and "sendTransaction" not in chain.calls
    [note] = receipts(ledger, "note", "withdraw_simulated")
    assert note["would_send_lamports"] == 249_995_000 and note["to"] == OWNER
    assert receipts(ledger, "withdraw") == []
    w.run(NOW + 20)  # too soon to look again
    w.run(NOW + 10 + PAPER_RECHECK_S)  # looked again: same answer, no new note
    assert len(receipts(ledger, "note", "withdraw_simulated")) == 1
    chain.balances[bot] = SOL  # the owner sent more from Phantom
    w.run(NOW + 20 + 2 * PAPER_RECHECK_S)
    assert [n["would_send_lamports"] for n in receipts(ledger, "note", "withdraw_simulated")] == [249_995_000,
                                                                                                    SOL - 5000]
    view = page_view(settings, state(ledger), NOW + 30 + 2 * PAPER_RECHECK_S)
    assert view is not None and view["level"] == "warn" and "would send 0.999995 SOL" in view["text"]
    assert "Nothing was sent" in view["text"] and "TRADING_MODE=live" in view["text"]
    assert chain.balances == {bot: SOL}  # nothing moved


def test_paper_mode_with_a_network_that_cannot_price_it_still_only_estimates(make_settings: Callable[..., Settings],
                                                                             ledger: Ledger, wallet: Any,
                                                                             fake_clock: FakeClock) -> None:
    chain = FakeChain({wallet.pubkey(): SOL})
    chain.fail = {"getFeeForMessage", "getMinimumBalanceForRentExemption"}
    w = Withdrawer(make_settings(WITHDRAW_TO=OWNER, BOT_WALLET_MODE="generated"), ledger, chain, wallet, fake_clock)
    assert w.run(NOW) == "paper"
    assert state(ledger)["paper"] == {"balance_lamports": SOL, "fee_lamports": BASE_FEE_LAMPORTS, "fee_exact": False,
                                      "would_send_lamports": SOL - BASE_FEE_LAMPORTS, "checked_at": NOW,
                                      "close_accounts": 0, "reclaim_lamports": 0, "reserve_lamports": 0}
    assert chain.sent == []


def test_paper_mode_with_an_empty_wallet_says_there_is_nothing_to_send(make_settings: Callable[..., Settings],
                                                                       ledger: Ledger, wallet: Any,
                                                                       fake_clock: FakeClock) -> None:
    chain = FakeChain({wallet.pubkey(): 0})
    chain.fund(OWNER, wallet.pubkey(), SOL, move=False)  # funded once, spent since
    settings = make_settings(WITHDRAW_TO=OWNER, BOT_WALLET_MODE="generated")
    assert Withdrawer(settings, ledger, chain, wallet, fake_clock).run(NOW) == "paper"
    view = page_view(settings, state(ledger), NOW + 1)
    assert view is not None and "nothing to send" in view["text"] and "holds 0 SOL" in view["text"]
    assert chain.sent == []


def test_without_a_wallet_there_is_nothing_to_send(make_settings: Callable[..., Settings], ledger: Ledger,
                                                   fake_clock: FakeClock) -> None:
    chain = FakeChain({})
    w = Withdrawer(make_settings(WITHDRAW_TO=OWNER), ledger, chain, None, fake_clock)
    assert w.run(NOW) == "no_wallet" and chain.calls == []


# --------------------------------------------------------------------------- the engine: buy nothing, sell everything


@pytest.fixture
def world(fake_http: FakeHttp, fake_clock: FakeClock) -> World:
    return make_world(fake_http, fake_clock)


@pytest.fixture
def make_rig(world: World, http_client: HttpClient, fake_clock: FakeClock, make_settings: Callable[..., Settings],
             tmp_path: Path) -> Iterator[Callable[..., Rig]]:
    ledgers: list[Ledger] = []

    def _make(*, withdraw: Any = None, ledger_path: Any = None, broker_factory: Any = None, **overrides: Any) -> Rig:
        settings = make_settings(**overrides)
        sources = build_sources(settings, http_client)
        ledger = Ledger(ledger_path or tmp_path / f"ledger{len(ledgers)}.db", clock=fake_clock)
        ledgers.append(ledger)
        broker = (broker_factory(world, ledger, fake_clock) if broker_factory is not None
                  else PaperBroker(sources.jupiter, ledger, settings, fake_clock))
        engine = Engine(settings, clock=fake_clock, ledger=ledger, crawler=Crawler(sources, settings, fake_clock),
                        cocoon=Cocoon(sources, settings, fake_clock), radar=Radar(sources, settings, fake_clock),
                        judge=Judge(settings, clock=fake_clock, ledger=ledger),
                        risk=RiskManager(settings, ledger, fake_clock), broker=broker, sources=sources,
                        withdraw=withdraw(settings, ledger) if withdraw is not None else None)
        return Rig(engine, ledger, broker, fake_clock, world, settings)

    yield _make
    for ledger in ledgers:
        ledger.close()


def test_withdraw_to_stops_buying_sells_everything_then_withdraws(make_rig: Callable[..., Rig], wallet: Any,
                                                                  tmp_path: Path) -> None:
    path = tmp_path / "shared.db"
    rig = make_rig(ledger_path=path)
    rig.tick()  # a normal paper bot buys the dip-rebound coin
    assert len(rig.ledger.open_positions()) == 1
    rig.ledger.close()

    chain = FakeChain({wallet.pubkey(): SOL})
    rig = make_rig(ledger_path=path, WITHDRAW_TO=OWNER, BOT_WALLET_MODE="generated",
                   withdraw=lambda settings, ledger: Withdrawer(settings, ledger, chain, wallet))
    results = rig.tick(5)
    assert rig.engine.handle_kill(rig.clock.now()) == "sell_all" and not rig.engine.entries_allowed
    assert rig.ledger.open_positions() == [] and results["withdraw"] == "ok"  # sold through the usual exit path
    [kill] = [r.payload for r in rig.ledger.receipts() if r.kind == "kill"]
    assert kill["mode"] == "sell_all"
    assert state(rig.ledger)["status"] in ("selling", "paper")
    rig.tick(rig.engine.withdraw.stage_s + 1)
    assert state(rig.ledger)["status"] == "paper" and chain.sent == []
    fills_before = len(rig.ledger.fills())
    rig.tick(600)  # the dip-rebound setup is still there: nothing is bought while WITHDRAW_TO is set
    assert len(rig.ledger.fills()) == fills_before and rig.ledger.open_positions() == []


def test_build_app_wires_the_bot_wallet_and_the_withdrawal(make_settings: Callable[..., Settings],
                                                           fake_clock: FakeClock) -> None:
    plain = build_app(make_settings(), fake_clock, session=FakeHttp())
    try:
        assert plain.engine.withdraw is None and plain.wallet is None  # nothing changes without the new settings
    finally:
        plain.close()
    settings = make_settings(BOT_WALLET_MODE="generated", WITHDRAW_TO=OWNER)
    app = build_app(settings, fake_clock, session=FakeHttp())
    try:
        assert isinstance(app.engine.withdraw, Withdrawer) and app.engine.withdraw.wallet is app.wallet
        assert app.ledger.get_kv("wallet.pubkey") == app.wallet.pubkey() == app.broker.taker
    finally:
        app.close()
    live_settings = live(make_settings)  # the same DATA_DIR: the wallet made in paper mode, now live
    app = build_app(live_settings, fake_clock, session=FakeHttp())
    try:
        assert app.broker.mode == "live" and app.broker.pubkey == app.wallet.pubkey()
        assert isinstance(app.engine.withdraw, Withdrawer)
    finally:
        app.close()


def test_the_audit_counts_a_confirmed_withdrawal_and_still_flags_missing_money(tmp_path: Path,
                                                                               fake_clock: FakeClock) -> None:
    from nightcrawler.audit import Auditor
    from test_audit import LIVE_EXPECTED, FakeBroker, book, winner_fills, winner_position

    with Ledger(tmp_path / "audit.db", clock=fake_clock) as led:
        book(led, winner_fills("live"), [winner_position()], mode="live")
        led.append_receipt("withdraw", {"mode": "live", "from": "BotWa11et", "to": OWNER, "lamports": 400_000_000,
                                        "fee_lamports": 5000, "signature": "sig"})
        led.append_receipt("note", {"event": "withdraw_simulated", "mode": "paper", "would_send_lamports": 10**9})
        sent = 400_005_000
        report = Auditor(led, FakeBroker("live", LIVE_EXPECTED - sent)).reconcile()
        assert report.ok and report.sol_drift_lamports == 0 and report.expected_sol_lamports == LIVE_EXPECTED - sent
        missing = Auditor(led, FakeBroker("live", LIVE_EXPECTED - sent - 50_000_000)).reconcile()
        assert not missing.ok and any("LESS SOL" in i for i in missing.issues)  # real missing money still fails
        broker = FakeBroker("live", LIVE_EXPECTED)
        broker.pubkey = "AnotherWa11et"  # type: ignore[attr-defined]  # another wallet's withdrawal is not ours
        assert Auditor(led, broker).reconcile().sol_drift_lamports == 0


# --------------------------------------------------------------------------- the page


def test_the_page_shows_the_deposit_address_and_how_to_fund_it(make_settings: Callable[..., Settings],
                                                                ledger: Ledger, wallet: Any) -> None:
    empty = build_page_state(ledger, make_settings(), NOW)["wallet"]
    assert empty["address"] is None and "BOT_WALLET_MODE=generated" in empty["note"]
    settings = make_settings(BOT_WALLET_MODE="generated")
    keystore.record(ledger, wallet)
    card = build_page_state(ledger, settings, NOW)["wallet"]
    assert card["address"] == wallet.pubkey() and card["help"] == FUND_HELP and card["own"] is True
    assert card["sol"] is None and "paper trades never spend it" in card["paper_note"]
    ledger.set_kv("bot_wallet.balance", {"address": wallet.pubkey(), "sol_lamports": 120_000_000,
                                         "checked_at": NOW - 60})
    page = build_page_state(ledger, settings, NOW)
    assert page["wallet"]["sol"] == pytest.approx(0.12) and page["wallet"]["checked_at"] == NOW - 60
    step3 = {i["id"]: i for i in page["ready"]["items"]}["wallet"]
    assert step3["done"] and "holds 0.12 SOL" in step3["reason"]
    ledger.set_kv("bot_wallet.balance", {"address": OWNER, "sol_lamports": 9 * SOL, "checked_at": NOW - 60})
    assert build_page_state(ledger, settings, NOW)["wallet"]["sol"] is None  # another wallet's reading never counts


@pytest.mark.parametrize(("status", "extra", "level", "words"), [
    ("selling", {"open_positions": 2}, "bad", "selling 2 coins first"),
    ("sending", {"pending": {"lamports": 431_245_000, "signature": "sig"}}, "bad", "sent 0.431245 SOL"),
    ("error", {"error": "the network refused the transfer", "retry_at": NOW + 300}, "bad", "about 5 min"),
    ("blocked", {"error": "WITHDRAW_TO is the bot's own address."}, "bad", "Can't withdraw"),
    ("done", {"sent_lamports": 431_245_000}, "warn", "Withdrawal done: 0.431245 SOL"),
    ("empty", {}, "warn", "Nothing to withdraw"),
])
def test_the_page_banner_is_red_while_withdrawing_and_shows_the_result(make_settings: Callable[..., Settings],
                                                                       ledger: Ledger, status: str,
                                                                       extra: dict[str, Any], level: str,
                                                                       words: str) -> None:
    settings = live(make_settings)
    ledger.set_kv("engine.kill_mode", "sell_all")  # what the engine applies for WITHDRAW_TO
    ledger.set_kv(KV_STATE, {"to": OWNER, "mode": "live", "status": status, "since": NOW - 60, **extra})
    page = build_page_state(ledger, settings, NOW)
    first = page["alerts"][0]
    assert first["level"] == level and words in first["text"], first
    assert page["withdraw"]["status"] == status and page["ready"]["ready"] is False
    assert not any("Kill switch is ON" in a["text"] for a in page["alerts"])  # one banner says it
    assert not [w for w in JARGON_WORDS if w in first["text"].lower()]


def test_without_withdraw_to_there_is_no_banner_but_the_last_withdrawal_stays(make_settings: Callable[..., Settings],
                                                                              ledger: Ledger) -> None:
    ledger.set_kv(KV_STATE, {"to": OWNER, "mode": "live", "status": "off",
                             "last": {"to": OWNER, "lamports": 500_000_000, "signature": "sig", "at": NOW - 3600}})
    page = build_page_state(ledger, make_settings(), NOW)
    assert page["withdraw"] is None and not any("ithdraw" in a["text"] for a in page["alerts"])
    assert page["wallet"]["last_withdrawal"] == {"sol": 0.5, "to": OWNER, "at": NOW - 3600, "signature": "sig"}


def test_money_taken_back_is_never_shown_as_a_trading_loss(make_settings: Callable[..., Settings],
                                                            ledger: Ledger) -> None:
    from nightcrawler.models import EquityPoint

    settings = live(make_settings)
    ledger.set_kv("live.start_lamports", SOL)
    ledger.set_kv("live.start_sol_usd", 100.0)
    ledger.record_equity(EquityPoint(ts=NOW - 30, equity_lamports=100_000_000, sol_usd=100.0, equity_usd=10.0,
                                     sol_lamports=100_000_000, positions_value_lamports=0, open_positions=0,
                                     mode="live"))
    before = build_page_state(ledger, settings, NOW)["money"]
    assert before["since_start"]["usd"] == pytest.approx(-90.0) and before["withdrawn_sol"] is None
    ledger.set_kv("withdraw.totals", {"lamports": SOL, "events": [[NOW - 60, SOL]]})  # 1 SOL went back today
    money = build_page_state(ledger, settings, NOW)["money"]
    assert money["usd"] == pytest.approx(10.0)  # what is in the wallet now ...
    assert money["since_start"]["usd"] == pytest.approx(10.0) and money["since_start"]["pct"] == pytest.approx(10.0)
    assert money["withdrawn_sol"] == pytest.approx(1.0)  # ... and the 1 SOL taken back is not a loss
    assert build_page_state(ledger, make_settings(), NOW)["money"]["withdrawn_sol"] is None  # paper: never


def test_the_page_script_copies_the_address_as_text_only(make_settings: Callable[..., Settings]) -> None:
    from nightcrawler.page import PAGE_CSP, render_page_html

    html = render_page_html(make_settings())
    assert "navigator.clipboard.writeText(address)" in html and "Copy address" in html
    assert 'id="wallet-body"' in html and "innerHTML" not in html
    assert "last.to.slice" not in html and "+ last.to +" in html  # W1: the destination in full, never 4…4
    assert "w.keep_note" in html  # KS-2: the volume holds the only copy of the key
    assert PAGE_CSP.startswith("default-src 'none'; script-src 'sha256-")


# --------------------------------------------------------------------------- review round 2 (W1 .. W7, KS-3)


def lookalikes(address: str) -> dict[str, list[str]]:
    """Cut-off and wrong-case versions of ``address`` that the settings and the offline checks still accept
    (Solana addresses have no checksum: most of them are valid addresses of nobody)."""
    variants: dict[str, list[str]] = {"cut_last": [address[:-1], address[:-2]], "cut_first": [address[1:]],
                                      "case": [address[:i] + address[i].swapcase() + address[i + 1:]
                                               for i in range(len(address)) if address[i].swapcase() != address[i]]}
    return {kind: [v for v in found if v != address and destination_problem(v, None) is None]
            for kind, found in variants.items()}


def test_a_mistyped_cut_off_or_look_alike_withdraw_to_never_gets_a_lamport(make_settings: Callable[..., Settings],
                                                                           ledger: Ledger, wallet: Any,
                                                                           fake_clock: FakeClock,
                                                                           monkeypatch: pytest.MonkeyPatch) -> None:
    """W1: no checksum, so the destination must be a wallet that exists AND funded the bot."""
    signed: list[str] = []
    real_sign = withdraw_mod.sign_transfer
    monkeypatch.setattr(withdraw_mod, "sign_transfer", lambda w, to, *a: signed.append(to) or real_sign(w, to, *a))
    bot = wallet.pubkey()
    variants = lookalikes(OWNER)
    assert all(variants.values()), {k: len(v) for k, v in variants.items()}  # each kind passes the offline checks
    for kind, found in variants.items():
        for target in found[:3]:
            make_settings(WITHDRAW_TO=target)  # the settings accept it (base58 of 32 bytes) ...
            chain = FakeChain({bot: 2 * SOL})
            w = Withdrawer(live(make_settings, WITHDRAW_TO=target), ledger, chain, wallet, fake_clock)
            for at in (NOW, NOW + ARM_S + 1, NOW + SELL_WAIT_S + 1_000):
                assert w.run(at) == "blocked", (kind, at)  # ... the chain does not
            assert chain.sent == [] and "does not exist" in state(ledger)["error"], kind
    assert signed == []

    lookalike = variants["case"][0]
    chain = FakeChain({bot: 2 * SOL})
    chain.accounts[lookalike] = dict(PLAIN_WALLET)  # a real wallet, but it never sent the bot anything
    chain.fund(lookalike, bot, 1_000)  # an address-poisoning look-alike sends dust to get into the history
    w = Withdrawer(live(make_settings, WITHDRAW_TO=lookalike), ledger, chain, wallet, fake_clock)
    assert w.run(NOW) == "blocked" and "sent" in state(ledger)["error"] and chain.sent == []
    assert w.run(NOW + ARM_S + BLOCKED_RECHECK) == "blocked" and signed == []
    view = page_view(live(make_settings, WITHDRAW_TO=lookalike), state(ledger), NOW + 1)
    assert view is not None and lookalike in view["text"]  # the FULL address, never 4…4

    chain = FakeChain({bot: 2 * SOL})  # the owner's own wallet funded it: allowed
    assert arm(Withdrawer(live(make_settings), ledger, chain, wallet, fake_clock)) == "sending"
    assert [decode(t)["to"] for t in chain.sent] == [OWNER]


BLOCKED_RECHECK = withdraw_mod.BLOCKED_RECHECK_S


def test_the_funding_wallet_is_found_beyond_the_first_page_and_needs_a_real_amount(
        make_settings: Callable[..., Settings], ledger: Ledger, wallet: Any, fake_clock: FakeClock) -> None:
    bot = wallet.pubkey()
    chain = FakeChain({bot: SOL}, funder=None)
    chain.accounts[OWNER] = dict(PLAIN_WALLET)
    chain.fund(OWNER, bot, MIN_FUNDING_LAMPORTS - 1, move=False)  # too small to count
    w = Withdrawer(live(make_settings), ledger, chain, wallet, fake_clock)
    assert w.run(NOW) == "blocked"
    assert "0.01 SOL" in state(ledger)["error"]
    chain.fund(OWNER, bot, MIN_FUNDING_LAMPORTS, move=False)
    for _ in range(1_500):  # the bot's trading pushes the deposit beyond the first 1000 signatures
        chain.history[bot].insert(0, b58encode(next(chain.counter).to_bytes(8, "big") * 8))
    assert w.run(NOW + BLOCKED_RECHECK) == "arming"  # the 10 minutes start once the address is accepted
    assert w.run(NOW + BLOCKED_RECHECK + ARM_S) == "sending"


def test_the_page_shows_the_full_address_and_nothing_is_sent_for_ten_minutes(make_settings: Callable[..., Settings],
                                                                             ledger: Ledger, wallet: Any,
                                                                             fake_clock: FakeClock) -> None:
    """W1: a 10-minute window to compare the FULL address with Phantom and cancel by deleting WITHDRAW_TO."""
    bot = wallet.pubkey()
    chain = FakeChain({bot: 431_250_000})
    settings = live(make_settings)
    w = Withdrawer(settings, ledger, chain, wallet, fake_clock)
    assert w.run(NOW) == "arming" and chain.sent == []
    view = page_view(settings, state(ledger), NOW + 1)
    assert view is not None and view["level"] == "bad" and OWNER in view["text"]
    assert "10 min" in view["text"] and "Delete WITHDRAW_TO" in view["text"] and "0.43125 SOL" in view["text"]
    assert w.run(NOW + ARM_S - 1) == "arming" and chain.sent == []
    cancelled = make_settings(TRADING_MODE="live", LIVE_CONFIRM=LIVE_CONFIRM_PHRASE, BOT_WALLET_MODE="generated",
                              DASHBOARD_TOKEN=STRONG_TOKEN)
    assert Withdrawer(cancelled, ledger, chain, wallet, fake_clock).run(NOW + ARM_S - 1) == "off"
    again = Withdrawer(settings, ledger, chain, wallet, fake_clock)
    assert again.run(NOW + ARM_S + 5) == "arming" and chain.sent == []  # set again: a new 10 minutes
    assert again.run(NOW + 2 * ARM_S + 5) == "sending" and len(chain.sent) == 1
    for status in ("selling", "sending", "done", "error"):
        shown = page_view(settings, {**state(ledger), "status": status}, NOW + 3 * ARM_S)
        assert shown is not None and OWNER in shown["text"], status


def test_a_pending_transfer_is_not_re_posted_once_withdraw_to_is_deleted_or_changed(
        make_settings: Callable[..., Settings], ledger: Ledger, wallet: Any, fake_clock: FakeClock) -> None:
    """W6: deleting WITHDRAW_TO stops re-broadcasts (the chain still decides what happened to the one sent)."""
    bot = wallet.pubkey()
    chain = FakeChain({bot: SOL})
    assert arm(Withdrawer(live(make_settings), ledger, chain, wallet, fake_clock)) == "sending"
    assert len(chain.sent) == 1
    deleted = make_settings(TRADING_MODE="live", LIVE_CONFIRM=LIVE_CONFIRM_PHRASE, BOT_WALLET_MODE="generated",
                            DASHBOARD_TOKEN=STRONG_TOKEN)
    w = Withdrawer(deleted, ledger, chain, wallet, fake_clock)
    for k in range(1, 4):
        w.run(NOW + k * REBROADCAST_S + 1)
    other = str(Keypair.from_seed(bytes([9]) * 32).pubkey())
    Withdrawer(live(make_settings, WITHDRAW_TO=other), ledger, chain, wallet, fake_clock).run(NOW + 5 * REBROADCAST_S)
    assert len(chain.sent) == 1 and withdraw_mod.has_pending(ledger)  # never re-posted ...
    assert w.kill_mode("off") == "sell_all"  # ... and nothing is bought while it may still land
    chain.land(chain.sent[0])
    assert w.run(NOW + 200) == "off" and len(receipts(ledger, "withdraw")) == 1
    assert not withdraw_mod.has_pending(ledger)


def test_a_withdrawal_that_landed_is_never_recorded_as_expired(make_settings: Callable[..., Settings],
                                                               ledger: Ledger, wallet: Any,
                                                               fake_clock: FakeClock, tmp_path: Path) -> None:
    """W5: a status node behind the height node must not turn a landed transfer into 'never sent'."""
    bot = wallet.pubkey()
    chain = FakeChain({bot: SOL})
    w = Withdrawer(live(make_settings), ledger, chain, wallet, fake_clock)
    arm(w)
    pending = state(ledger)["pending"]
    chain.land(chain.sent[0])
    chain.hidden.add(pending["signature"])  # this node has not seen it yet ...
    chain.height = pending["last_valid_block_height"] + 5  # ... and that one is past its blockhash
    w.run(NOW + 60)
    assert receipts(ledger, "withdraw") == [] and chain.balances[bot] == 0
    assert len(chain.sent) == 1  # nothing new was sent (there is nothing left to send anyway)
    chain.hidden.clear()  # the node catches up
    for k in range(1, 4):
        w.run(NOW + 60 + k * 61)
    [receipt] = receipts(ledger, "withdraw")
    assert receipt["signature"] == pending["signature"] and receipt["lamports"] == SOL - BASE_FEE_LAMPORTS
    assert state(ledger)["status"] == "done" and state(ledger)["sent_lamports"] == SOL - BASE_FEE_LAMPORTS
    assert withdraw_mod.withdrawn_lamports(ledger, NOW + 1_000, NOW - 1)[0] == SOL - BASE_FEE_LAMPORTS

    # and when the transaction itself can be fetched, it is recognised at once
    with Ledger(tmp_path / "other.db", clock=fake_clock) as other:
        chain2 = FakeChain({bot: SOL})
        w2 = Withdrawer(live(make_settings), other, chain2, wallet, fake_clock)
        arm(w2)
        sig = state(other)["pending"]["signature"]
        chain2.land(chain2.sent[0])
        chain2.parsed[sig] = {"slot": 9, "meta": {"err": None}}  # getTransaction knows it ...
        chain2.statuses = {}  # ... the status node does not
        chain2.height = 10_000
        assert w2.run(NOW + 60) == "done" and len(receipts(other, "withdraw")) == 1
        assert receipts(other, "note", "withdraw_expired") == []


def test_the_starting_balance_is_recorded_before_the_first_live_transfer(make_settings: Callable[..., Settings],
                                                                         ledger: Ledger, wallet: Any,
                                                                         fake_clock: FakeClock) -> None:
    """W4 (unit): without a recorded live start (the price source was down), the withdrawal records it first."""
    bot = wallet.pubkey()
    chain = FakeChain({bot: 2 * SOL})
    assert ledger.get_kv("live.start_lamports") is None
    assert arm(Withdrawer(live(make_settings), ledger, chain, wallet, fake_clock)) == "sending"
    assert ledger.get_kv("live.start_lamports") == 2 * SOL
    [note] = receipts(ledger, "note", "live_start")
    assert note["start_lamports"] == 2 * SOL and note["by"] == "withdraw"


def test_empty_coin_accounts_are_closed_before_the_sol_is_sent(make_settings: Callable[..., Settings],
                                                               ledger: Ledger, wallet: Any,
                                                               fake_clock: FakeClock) -> None:
    """KS-3: nobody else can sign for this wallet, so the bot closes its emptied token accounts itself (each
    gives back its ~0.002 SOL deposit) and only then sends everything."""
    bot = wallet.pubkey()
    chain = FakeChain({bot: SOL})
    empty = [chain.token_account(bot, mint=f"mint{i}") for i in range(3)]
    t22 = chain.token_account(bot, mint="mint22", lamports=2_500_000, program=TOKEN_2022_PROGRAM)
    held = chain.token_account(bot, mint="mintheld", amount=5_000)  # still holds coins: never closed
    frozen = chain.token_account(bot, mint="mintfrozen", state="frozen")  # cannot be closed
    stuck = chain.token_account(bot, mint="mintstuck")  # its close authority is someone else's
    chain.sim_err_for = lambda tx: ({"InstructionError": [0, {"Custom": 4}]}
                                    if any(c[0] == stuck for c in decode_any(tx).get("closes", [])) else None)
    w = Withdrawer(live(make_settings), ledger, chain, wallet, fake_clock)
    assert arm(w) == "closing"
    [close_tx] = chain.sent
    closed = decode_any(close_tx)
    assert closed["kind"] == "close" and closed["payer"] == bot
    assert sorted(c[0] for c in closed["closes"]) == sorted([*empty, t22])
    assert all(c[1] == bot and c[2] == bot for c in closed["closes"])  # the deposits come back to the bot
    assert w.run(NOW + 5) == "closing"  # waits for the network
    chain.land(close_tx)
    reclaimed = 3 * 2_039_280 + 2_500_000
    assert w.run(NOW + 10) == "sending"
    [note] = receipts(ledger, "note", "accounts_closed")
    assert note["reclaimed_lamports"] == reclaimed and note["accounts"] == 4 and note["fee_lamports"] == 5000
    tx = decode(chain.sent[-1])
    assert tx["lamports"] == SOL + reclaimed - 5000 - BASE_FEE_LAMPORTS
    chain.land(chain.sent[-1])
    assert chain.balances[bot] == 0 and set(chain.token_accounts) == {held, frozen, stuck}
    assert w.run(NOW + 20 + RECHECK_S) == "done" and len(chain.sent) == 2  # nothing closed twice

    from nightcrawler.audit import Auditor
    from test_audit import FakeBroker

    ledger.set_kv("live.start_lamports", SOL)
    broker = FakeBroker("live", 0)
    broker.pubkey = bot  # type: ignore[attr-defined]
    report = Auditor(ledger, broker).reconcile()
    assert report.expected_sol_lamports == 0 and report.sol_drift_lamports == 0


def test_paper_mode_counts_the_deposits_it_would_get_back(make_settings: Callable[..., Settings], ledger: Ledger,
                                                          wallet: Any, fake_clock: FakeClock) -> None:
    bot = wallet.pubkey()
    chain = FakeChain({bot: SOL})
    for i in range(2):
        chain.token_account(bot, mint=f"m{i}")
    settings = make_settings(BOT_WALLET_MODE="generated", WITHDRAW_TO=OWNER)
    assert Withdrawer(settings, ledger, chain, wallet, fake_clock).run(NOW) == "paper"
    paper = state(ledger)["paper"]
    assert paper["close_accounts"] == 2 and paper["reclaim_lamports"] == 2 * 2_039_280
    assert paper["would_send_lamports"] == SOL + 2 * 2_039_280 - 5000 - BASE_FEE_LAMPORTS
    assert chain.sent == [] and chain.simulated == [] and len(chain.token_accounts) == 2


def test_after_a_live_withdrawal_real_money_is_not_traded_until_the_bot_ran_in_paper(
        make_settings: Callable[..., Settings], ledger: Ledger, wallet: Any, fake_clock: FakeClock,
        tmp_path: Path) -> None:
    """W2: deleting WITHDRAW_TO but leaving TRADING_MODE=live must not trade the next deposit by surprise."""
    bot = wallet.pubkey()
    chain = FakeChain({bot: SOL})
    w = Withdrawer(live(make_settings), ledger, chain, wallet, fake_clock)
    arm(w)
    chain.land(chain.sent[0])
    assert w.run(NOW + 5) == "done"
    done = page_view(live(make_settings), state(ledger), NOW + 6)
    assert done is not None and "TRADING_MODE=paper" in done["text"]
    still_live = make_settings(TRADING_MODE="live", LIVE_CONFIRM=LIVE_CONFIRM_PHRASE, BOT_WALLET_MODE="generated",
                               DASHBOARD_TOKEN=STRONG_TOKEN)
    held = Withdrawer(still_live, ledger, chain, wallet, fake_clock)
    assert held.run(NOW + 60) == "off" and held.kill_mode("off") == "stop"  # buys nothing ...
    assert held.kill_mode("sell_all") == "sell_all"
    page = build_page_state(ledger, still_live, NOW + 61)
    assert page["withdraw"] is not None and "TRADING_MODE=paper" in page["withdraw"]["text"]
    assert page["alerts"][0]["text"] == page["withdraw"]["text"]
    assert not any("Kill switch is ON" in a["text"] for a in page["alerts"])
    paper = Withdrawer(make_settings(BOT_WALLET_MODE="generated"), ledger, chain, wallet, fake_clock)
    assert paper.run(NOW + 120) == "off"  # ... until the owner switched to paper once
    assert held.kill_mode("off") == "off" and build_page_state(ledger, still_live, NOW + 121)["withdraw"] is None
    assert receipts(ledger, "note", "withdraw_hold_cleared")


def test_build_app_keeps_the_hold_and_the_engine_applies_it(make_settings: Callable[..., Settings],
                                                            fake_clock: FakeClock) -> None:
    settings = make_settings(BOT_WALLET_MODE="generated")
    app = build_app(settings, fake_clock, session=FakeHttp())  # paper: makes the wallet
    try:
        app.ledger.set_kv(withdraw_mod.KV_HOLD, {"since": NOW, "to": OWNER})
    finally:
        app.close()
    still_live = make_settings(TRADING_MODE="live", LIVE_CONFIRM=LIVE_CONFIRM_PHRASE, BOT_WALLET_MODE="generated",
                               DASHBOARD_TOKEN=STRONG_TOKEN)
    app = build_app(still_live, fake_clock, session=FakeHttp())
    try:
        assert isinstance(app.engine.withdraw, Withdrawer)
        assert app.engine.handle_kill(fake_clock.now()) == "stop" and not app.engine.entries_allowed
    finally:
        app.close()


def test_the_paper_banner_names_everything_a_real_withdrawal_needs(make_settings: Callable[..., Settings],
                                                                   ledger: Ledger) -> None:
    """W2 / KS-4: live mode refuses to start without a strong DASHBOARD_TOKEN, so the banner says so."""
    ledger.set_kv(KV_STATE, {"to": OWNER, "mode": "paper", "status": "paper", "since": NOW - 60,
                             "paper": {"would_send_lamports": SOL, "fee_lamports": 5000, "balance_lamports": SOL}})
    weak = page_view(make_settings(WITHDRAW_TO=OWNER), state(ledger), NOW)
    assert weak is not None and "DASHBOARD_TOKEN" in weak["text"] and "24" in weak["text"]
    strong = page_view(make_settings(WITHDRAW_TO=OWNER, DASHBOARD_TOKEN=STRONG_TOKEN), state(ledger), NOW)
    assert strong is not None and "LIVE_CONFIRM=I_ACCEPT_REAL_MONEY_RISK" in strong["text"]
    assert "you already have" in strong["text"]


def test_an_engine_whose_price_source_fails_at_the_first_live_boot_books_the_withdrawal_right(
        make_rig: Callable[..., Rig], wallet: Any) -> None:
    """W4: the first live start cannot price SOL (keyless Jupiter under 429); the withdrawal must not show
    the owner's own money as a profit afterwards."""
    from test_engine import SOL_USD, FakeLiveBroker

    from nightcrawler.audit import Auditor

    bot = wallet.pubkey()
    chain = FakeChain({bot: 2 * SOL})
    brokers: list[Any] = []

    def broker(world: World, ledger: Ledger, clock: FakeClock) -> Any:
        b = FakeLiveBroker(world, ledger, clock, sol=2 * SOL)
        b.sol_price_error = RuntimeError("429 Too Many Requests")
        brokers.append(b)
        return b

    rig = make_rig(broker_factory=broker, withdraw=lambda settings, ledger: Withdrawer(settings, ledger, chain, wallet),
                   **live_env())
    results = rig.tick()
    assert results["live_start"].startswith("error") and results["withdraw"] == "ok"
    assert state(rig.ledger)["status"] == "arming"
    rig.tick(ARM_S + 1)
    assert state(rig.ledger)["status"] == "sending" and rig.ledger.get_kv("live.start_lamports") == 2 * SOL
    chain.land(chain.sent[0])
    brokers[0].sol = chain.balances[bot]
    rig.tick(rig.engine.withdraw.stage_s + 1)
    assert state(rig.ledger)["status"] == "done"
    brokers[0].sol_price_error = None  # the price source is back
    rig.tick(rig.settings.equity_interval_s + 1)
    assert rig.engine.entries_allowed is False  # WITHDRAW_TO still set: buys nothing
    money = build_page_state(rig.ledger, rig.settings, rig.clock.now())["money"]
    assert money["since_start"]["usd"] == pytest.approx(-BASE_FEE_LAMPORTS / SOL * SOL_USD, abs=1e-6)  # not +$
    assert money["withdrawn_sol"] == pytest.approx((2 * SOL - BASE_FEE_LAMPORTS) / SOL)
    report = Auditor(rig.ledger, brokers[0]).reconcile()
    assert report.expected_sol_lamports == 0 and report.sol_drift_lamports == 0


def live_env() -> dict[str, str]:
    return {"TRADING_MODE": "live", "LIVE_CONFIRM": LIVE_CONFIRM_PHRASE, "BOT_WALLET_MODE": "generated",
            "DASHBOARD_TOKEN": STRONG_TOKEN, "WITHDRAW_TO": OWNER}


def test_withdrawn_sol_is_added_back_only_once_it_shows_in_an_equity_point(make_settings: Callable[..., Settings],
                                                                           ledger: Ledger) -> None:
    """W7: a withdrawal after the latest equity point is not in that point yet: adding it back would count it
    twice. Today's figure only adds back what landed after today's first point."""
    from nightcrawler.models import EquityPoint

    settings = live(make_settings)

    def point(ts: float, lamports: int) -> None:
        ledger.record_equity(EquityPoint(ts=ts, equity_lamports=lamports, sol_usd=100.0,
                                         equity_usd=lamports / SOL * 100, sol_lamports=lamports,
                                         positions_value_lamports=0, open_positions=0, mode="live"))

    ledger.set_kv("live.start_lamports", SOL)
    ledger.set_kv("live.start_sol_usd", 100.0)
    point(NOW - 30, SOL)
    sent = SOL - BASE_FEE_LAMPORTS
    withdraw_mod._count_withdrawn(ledger, sent, NOW)
    ledger.set_kv(KV_STATE, {"to": OWNER, "mode": "live", "status": "done", "since": NOW - 700,
                             "sent_lamports": sent, "balance_after": {"lamports": 0, "at": NOW},
                             "last": {"to": OWNER, "lamports": sent, "signature": "sig", "at": NOW}})
    page = build_page_state(ledger, settings, NOW + 6)
    assert page["money"]["since_start"]["usd"] == pytest.approx(0.0)  # not +99.9995
    assert page["money"]["today"]["usd"] == pytest.approx(0.0)
    assert page["wallet"]["sol"] == 0.0  # the wallet card reads the balance after the transfer
    point(NOW + 60, 0)
    page = build_page_state(ledger, settings, NOW + 61)
    assert page["money"]["since_start"]["usd"] == pytest.approx(-BASE_FEE_LAMPORTS / SOL * 100)
    assert page["money"]["today"]["usd"] == pytest.approx(-BASE_FEE_LAMPORTS / SOL * 100)

    # a withdrawal just after UTC midnight, before that day's first point, is not "today's" result
    midnight = (NOW // 86_400 + 1) * 86_400
    ledger.set_kv("withdraw.totals", None)
    ledger.set_kv("live.start_lamports", 2 * SOL)
    point(midnight - 100, 2 * SOL)
    withdraw_mod._count_withdrawn(ledger, sent, midnight + 10)
    point(midnight + 60, SOL)
    page = build_page_state(ledger, settings, midnight + 70)
    assert page["money"]["today"]["usd"] == pytest.approx(0.0)
    assert page["money"]["since_start"]["usd"] == pytest.approx(-BASE_FEE_LAMPORTS / SOL * 100)
