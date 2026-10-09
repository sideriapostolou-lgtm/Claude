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
    BASE_FEE_LAMPORTS,
    KV_STATE,
    PAPER_RECHECK_S,
    REBROADCAST_S,
    RECHECK_S,
    RENT_EXEMPT_MIN_LAMPORTS,
    RETRY_S,
    SELL_WAIT_S,
    Withdrawer,
    account_problem,
    destination_problem,
    page_view,
    withdrawable_lamports,
)
from test_engine import Rig  # noqa: E402
from world import World, make_world  # noqa: E402

NOW = 1_791_475_200.0
SOL = 1_000_000_000
STRONG_TOKEN = "withdraw-dashboard-passw0rd-8d2f6a1c9e"
OWNER = str(Keypair.from_seed(bytes([7]) * 32).pubkey())  # an on-curve wallet address (the owner's Phantom)
TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
SYSTEM = "11111111111111111111111111111111"
JARGON_WORDS = ("lamport", "mint", "slippage", "ledger", " kv", "bps")


# --------------------------------------------------------------------------- a tiny Solana


class FakeChain:
    """Balances, one blockhash at a time, a signature table and the runtime's fee and rent rules for a fee payer
    that drains itself. Records every call; ``land()`` applies a posted transfer the way the runtime would."""

    def __init__(self, balances: dict[str, int], *, fee: int = BASE_FEE_LAMPORTS,
                 rent_min: int = RENT_EXEMPT_MIN_LAMPORTS) -> None:
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
        if method == "getLatestBlockhash":
            return {**ctx, "value": {"blockhash": self.blockhash, "lastValidBlockHeight": self.last_valid}}
        if method == "getFeeForMessage":
            return {**ctx, "value": self.fee}
        if method == "getMinimumBalanceForRentExemption":
            return self.rent_min
        if method == "getBlockHeight":
            return self.height
        if method == "getAccountInfo":
            return {**ctx, "value": self.accounts.get(params[0])}
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
        return {"err": self.sim_err, "logs": [], "units_consumed": 150}

    def signature_status(self, signature: str) -> dict[str, Any] | None:
        self._raise("getSignatureStatuses")
        return self.statuses.get(signature)

    def land(self, tx_b64: str) -> None:
        """Apply the transfer like the runtime: fee first (the payer must stay rent-exempt or reach 0), then the
        transfer (the payer ends at 0 or rent-exempt; a new destination must become rent-exempt)."""
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
    assert account_problem(None) is None  # a brand-new address is fine (the amount covers its rent)
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
    assert w.run(NOW) == "sending"
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
    assert withdraw_mod.withdrawn_lamports(ledger, NOW + 5) == (431_245_000, 431_245_000)
    assert withdraw_mod.withdrawn_lamports(ledger, NOW + 86_400) == (431_245_000, 0)  # the next UTC day


def test_a_restart_never_sends_a_second_transfer(make_settings: Callable[..., Settings], ledger: Ledger, wallet: Any,
                                                 fake_clock: FakeClock) -> None:
    bot = wallet.pubkey()
    chain = FakeChain({bot: 2 * SOL})
    settings = live(make_settings)
    chain.fail.add("sendTransaction")  # the first post dies on the way (or the process dies right after)
    assert Withdrawer(settings, ledger, chain, wallet, fake_clock).run(NOW) == "sending"
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
    w.run(NOW)
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
    w.run(NOW)
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
    assert w.run(NOW) == "error" and chain.sent == []
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
    w = Withdrawer(live(make_settings), ledger, chain, wallet, fake_clock)
    assert w.run(NOW) == "empty" and chain.sent == []
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
    assert w.run(NOW, open_positions=2) == "selling" and chain.calls == []  # not even a read while selling
    assert w.run(NOW + 60, open_positions=0, pending_swaps=1) == "selling"
    assert w.run(NOW + SELL_WAIT_S, open_positions=1) == "sending"  # a coin nobody buys: the SOL goes anyway
    chain.land(chain.sent[0])
    w.run(NOW + SELL_WAIT_S + 5, open_positions=1)
    view = page_view(live(make_settings), state(ledger), NOW + SELL_WAIT_S + 6)
    assert view is not None and view["status"] == "done" and "1 coin could not be sold" in view["text"]


def test_a_transfer_in_flight_is_followed_up_after_withdraw_to_is_deleted(make_settings: Callable[..., Settings],
                                                                          ledger: Ledger, wallet: Any,
                                                                          fake_clock: FakeClock) -> None:
    bot = wallet.pubkey()
    chain = FakeChain({bot: SOL})
    Withdrawer(live(make_settings), ledger, chain, wallet, fake_clock).run(NOW)
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
                                      "would_send_lamports": SOL - BASE_FEE_LAMPORTS, "checked_at": NOW}
    assert chain.sent == []


def test_paper_mode_with_an_empty_wallet_says_there_is_nothing_to_send(make_settings: Callable[..., Settings],
                                                                       ledger: Ledger, wallet: Any,
                                                                       fake_clock: FakeClock) -> None:
    chain = FakeChain({wallet.pubkey(): 0})
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

    def _make(*, withdraw: Any = None, ledger_path: Any = None, **overrides: Any) -> Rig:
        settings = make_settings(**overrides)
        sources = build_sources(settings, http_client)
        ledger = Ledger(ledger_path or tmp_path / f"ledger{len(ledgers)}.db", clock=fake_clock)
        ledgers.append(ledger)
        broker = PaperBroker(sources.jupiter, ledger, settings, fake_clock)
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
    ledger.set_kv("withdraw.totals", {"lamports": SOL, "by_day": {"2026-10-08": SOL}})  # 1 SOL went back today
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
    assert PAGE_CSP.startswith("default-src 'none'; script-src 'sha256-")
