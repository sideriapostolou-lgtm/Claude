"""Wallet: Phantom base58 + solana-keygen JSON formats, generation, signing, redaction.

Keys are generated fresh per test and never funded.
"""

from __future__ import annotations

import base64
import copy
import io
import json
import logging
import pickle
import sys
import traceback

import pytest
from solders.hash import Hash
from solders.keypair import Keypair
from solders.message import MessageV0
from solders.pubkey import Pubkey
from solders.signature import Signature
from solders.system_program import TransferParams, transfer
from solders.transaction import VersionedTransaction

from nightcrawler.base58 import b58encode, is_pubkey
from nightcrawler.broker.base import LiveNotAllowed
from nightcrawler.broker.wallet import PHANTOM_IMPORT_HELP, Wallet, WalletError, generate_new, load_keypair
from nightcrawler.config import Secret
from nightcrawler.logging_setup import REDACTED, setup_logging


@pytest.fixture
def keypair() -> Keypair:
    return Keypair()


@pytest.fixture
def secret58(keypair: Keypair) -> str:
    return b58encode(bytes(keypair))


def assert_no_secret(text: str, keypair: Keypair) -> None:
    raw = bytes(keypair)
    assert b58encode(raw) not in text
    assert str(list(raw)) not in text and json.dumps(list(raw)) not in text
    assert repr(raw) not in text and raw.hex() not in text


def test_base58_phantom_export_loads(keypair, secret58) -> None:
    wallet = load_keypair(secret58)
    assert wallet.pubkey() == str(keypair.pubkey())
    assert is_pubkey(wallet.pubkey())
    assert wallet.keypair().pubkey() == keypair.pubkey()


def test_json_byte_array_from_solana_keygen_loads(keypair) -> None:
    keygen_file = "[\n  " + ",\n  ".join(str(b) for b in bytes(keypair)) + "\n]\n"
    assert load_keypair(keygen_file).pubkey() == str(keypair.pubkey())
    assert load_keypair(json.dumps(list(bytes(keypair)))).pubkey() == str(keypair.pubkey())


def test_secret_objects_and_surrounding_whitespace_are_accepted(keypair, secret58) -> None:
    assert load_keypair(Secret(f"  {secret58}\n")).pubkey() == str(keypair.pubkey())


@pytest.mark.parametrize("bad, message", [
    ("", "empty"),
    ("0OIl" * 22, "neither base58"),
    ("[1, 2, 3", "does not parse"),
    ("[" + ",".join(["7"] * 63) + "]", "64 integers"),
    ("[" + ",".join(["256"] * 64) + "]", "64 integers"),
    ("[" + ",".join(["true"] * 64) + "]", "64 integers"),
])
def test_malformed_secrets_are_rejected(bad: str, message: str) -> None:
    with pytest.raises(WalletError, match=message):
        load_keypair(bad)


def test_the_address_instead_of_the_secret_gets_a_helpful_error(keypair) -> None:
    with pytest.raises(WalletError, match="decodes to 32 bytes"):
        load_keypair(str(keypair.pubkey()))


def test_errors_never_contain_the_secret(keypair, secret58) -> None:
    raw = bytes(keypair)
    for bad in (secret58[:-3], secret58 + "0", json.dumps(list(raw))[:-1], json.dumps(list(raw) + [1])):
        with pytest.raises(WalletError) as info:
            load_keypair(bad)
        rendered = "".join(traceback.format_exception(info.value))
        assert bad not in rendered
        assert_no_secret(rendered, keypair)


def test_corrupted_secret_whose_public_half_mismatches_is_rejected(keypair) -> None:
    tampered = bytes(keypair)[:32] + bytes(Keypair().pubkey())
    with pytest.raises(WalletError, match="corrupted"):
        load_keypair(b58encode(tampered))
    with pytest.raises(WalletError, match="64 bytes"):
        Wallet(bytes(keypair)[:63])


def test_repr_and_str_show_only_the_address(keypair, secret58) -> None:
    wallet = load_keypair(secret58)
    for text in (repr(wallet), str(wallet), f"{wallet}", repr([wallet])):
        assert wallet.pubkey() in text
        assert_no_secret(text, keypair)


def test_wallets_refuse_to_be_pickled_or_copied(secret58) -> None:
    wallet = load_keypair(secret58)
    with pytest.raises(TypeError):
        pickle.dumps(wallet)
    with pytest.raises(TypeError):
        copy.deepcopy(wallet)
    with pytest.raises(TypeError):
        vars(wallet)


def test_secret_base58_round_trips_for_the_wallet_new_command(keypair, secret58) -> None:
    assert load_keypair(secret58).secret_base58() == secret58


def test_generate_new_returns_a_fresh_usable_keypair() -> None:
    wallet, secret = generate_new()
    assert load_keypair(secret).pubkey() == wallet.pubkey()
    assert generate_new()[0].pubkey() != wallet.pubkey()
    assert "Import Private Key" in PHANTOM_IMPORT_HELP


def test_without_solders_the_address_still_works_but_signing_does_not(secret58, keypair, monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "solders", None)
    wallet = load_keypair(secret58)
    assert wallet.pubkey() == str(keypair.pubkey())
    with pytest.raises(LiveNotAllowed, match=r"nightcrawler\[live\]"):
        wallet.keypair()
    with pytest.raises(LiveNotAllowed, match=r"nightcrawler\[live\]"):
        generate_new()


def test_load_registers_every_encoding_with_the_log_redaction_filter(keypair, secret58) -> None:
    stream = io.StringIO()
    root_level = logging.getLogger().level
    redaction = setup_logging("INFO", stream=stream)
    try:
        load_keypair(secret58, redaction_filter=redaction)
        raw = bytes(keypair)
        log = logging.getLogger("nightcrawler.test_wallet")
        log.info("oops %s", secret58)
        log.info("oops %s", json.dumps(list(raw)))
        log.info("oops %s", json.dumps(list(raw), separators=(",", ":")))
    finally:
        root = logging.getLogger()
        root.handlers = [h for h in root.handlers if not getattr(h, "_nightcrawler", False)]
        root.setLevel(root_level)
    output = stream.getvalue()
    assert output.count(REDACTED) == 3
    assert_no_secret(output, keypair)


def test_sign_transaction_produces_a_verifying_signature(keypair, secret58) -> None:
    ix = transfer(TransferParams(from_pubkey=keypair.pubkey(), to_pubkey=Pubkey.new_unique(), lamports=1))
    message = MessageV0.try_compile(keypair.pubkey(), [ix], [], Hash.new_unique())
    unsigned = base64.b64encode(bytes(VersionedTransaction.populate(message, [Signature.default()]))).decode()

    signed = VersionedTransaction.from_bytes(base64.b64decode(load_keypair(secret58).sign_transaction_b64(unsigned)))
    assert signed.verify_with_results() == [True]
    assert bytes(signed) == bytes(VersionedTransaction(message, [keypair]))


def test_signing_refuses_garbage_and_foreign_transactions(secret58) -> None:
    wallet = load_keypair(secret58)
    with pytest.raises(WalletError, match="not a base64"):
        wallet.sign_transaction_b64("definitely not a transaction")
    with pytest.raises(WalletError, match="not a base64"):
        wallet.sign_transaction_b64(base64.b64encode(b"\x01garbage").decode())
    other = Keypair()
    ix = transfer(TransferParams(from_pubkey=other.pubkey(), to_pubkey=Pubkey.new_unique(), lamports=1))
    message = MessageV0.try_compile(other.pubkey(), [ix], [], Hash.new_unique())
    foreign = base64.b64encode(bytes(VersionedTransaction.populate(message, [Signature.default()]))).decode()
    with pytest.raises(WalletError, match="does not require this wallet"):
        wallet.sign_transaction_b64(foreign)
