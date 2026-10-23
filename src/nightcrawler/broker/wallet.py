"""Bot wallet keypair handling (owner: O5). The secret NEVER appears in logs, repr or errors.

Accepted secret formats (``BOT_WALLET_SECRET``):

* base58 string of a 64-byte secret key (Phantom "Export Private Key");
* JSON array of 64 ints 0-255 (``solana-keygen`` file contents).

Byte layout: ``secret[0:32]`` = ed25519 seed, ``secret[32:64]`` = public key,
so the address can be derived WITHOUT ``solders`` (``wallet show`` works
without the live extra). When ``solders`` is installed, the public half is
also verified against the seed (a corrupted secret is refused).

On load, register BOTH encodings of the secret with the logging redaction
filter (``logging_setup.RedactionFilter.add_secret``) when one is given.
"""

from __future__ import annotations

import base64
import json
from typing import Any

from nightcrawler.base58 import b58decode, b58encode
from nightcrawler.broker.base import LiveNotAllowed, require_solders
from nightcrawler.config import Secret

__all__ = ["WalletError", "Wallet", "load_keypair", "generate_new", "PHANTOM_IMPORT_HELP"]

PHANTOM_IMPORT_HELP = (
    "To view this wallet in Phantom: Settings -> Manage Accounts -> Add / Connect Wallet -> "
    "Import Private Key, then paste the secret. Use this wallet ONLY for the bot and fund it "
    "with no more than you can lose."
)

SECRET_LEN = 64


class WalletError(ValueError):
    """Bad secret format. The message never contains the secret."""


class Wallet:
    """A loaded bot keypair. ``repr``/``str`` show only the public address.

    The secret is held in a :class:`~nightcrawler.config.Secret` (prints as
    ``***``); the object refuses to be pickled or copied by value.
    """

    __slots__ = ("_secret", "_pubkey")

    def __init__(self, secret_bytes: bytes) -> None:
        """``secret_bytes``: exactly 64 bytes (seed + pubkey). Raises ``WalletError`` otherwise."""
        if not isinstance(secret_bytes, (bytes, bytearray)) or len(secret_bytes) != SECRET_LEN:
            raise WalletError("a wallet secret must be exactly 64 bytes (32-byte seed + 32-byte public key)")
        secret_bytes = bytes(secret_bytes)
        _verify_public_half(secret_bytes)
        self._secret = Secret(b58encode(secret_bytes))
        self._pubkey = b58encode(secret_bytes[32:])

    def pubkey(self) -> str:
        """Base58 public address."""
        return self._pubkey

    def keypair(self) -> Any:
        """``solders.keypair.Keypair`` (requires the ``live`` extra; raises ``LiveNotAllowed`` otherwise)."""
        solders = require_solders()
        return solders.keypair.Keypair.from_bytes(b58decode(self._secret.reveal()))

    def sign_transaction_b64(self, tx_b64: str) -> str:
        """Deserialize an unsigned Ultra ``VersionedTransaction`` (base64), sign it, return base64.

        Only this wallet's signature slot is filled; other required signatures
        (e.g. Ultra's fee payer on a gasless swap) are left for their owner.
        For a single-signer transaction the result is byte-identical to
        ``VersionedTransaction(tx.message, [keypair])``. Raises ``WalletError``
        when the payload is not a transaction or does not need this wallet's signature.
        """
        solders = require_solders()
        tx = _decode_transaction(tx_b64)
        message = tx.message
        keypair = self.keypair()
        required = message.header.num_required_signatures
        signers = list(message.account_keys[:required])
        signatures = list(tx.signatures)
        if keypair.pubkey() not in signers:
            raise WalletError("the transaction does not require this wallet's signature")
        if len(signatures) != required:
            raise WalletError(f"malformed transaction: {len(signatures)} signature slots for {required} signers")
        signatures[signers.index(keypair.pubkey())] = keypair.sign_message(
            solders.message.to_bytes_versioned(message))
        signed = solders.transaction.VersionedTransaction.populate(message, signatures)
        return base64.b64encode(bytes(signed)).decode("ascii")

    def secret_base58(self) -> str:
        """The secret in Phantom (base58) format. ONLY for the ``wallet new`` command output."""
        return self._secret.reveal()

    def __repr__(self) -> str:
        return f"Wallet(pubkey={self._pubkey!r})"

    def __reduce__(self) -> Any:  # refuse to pickle/copy secrets by accident
        raise TypeError("Wallet objects cannot be pickled or copied")


def load_keypair(secret: str | Secret, redaction_filter: Any | None = None) -> Wallet:
    """Parse a base58 or JSON-array secret into a :class:`Wallet`.

    Whitespace is stripped. Raises :class:`WalletError` (message without the
    secret) on wrong length/format or a pubkey/seed mismatch. With
    ``redaction_filter``, the raw input, its base58 form and its JSON-array
    forms are registered as secrets so they can never reach the logs.
    """
    raw = (secret.reveal() if isinstance(secret, Secret) else str(secret)).strip()
    if not raw:
        raise WalletError("the wallet secret is empty")
    secret_bytes = _parse_json_secret(raw) if raw.startswith("[") else _parse_base58_secret(raw)
    if redaction_filter is not None:
        for encoding in _secret_encodings(raw, secret_bytes):
            redaction_filter.add_secret(encoding)
    return Wallet(secret_bytes)


def generate_new() -> tuple[Wallet, str]:
    """Create a fresh random keypair with ``solders.keypair.Keypair()`` (needs the ``live``
    extra; raises ``LiveNotAllowed`` with install instructions otherwise).
    Returns ``(wallet, secret_base58)``.

    The CLI prints the address and the secret ONCE with a big warning and
    :data:`PHANTOM_IMPORT_HELP`; nothing is written to disk or logs.
    """
    solders = require_solders()
    wallet = Wallet(bytes(solders.keypair.Keypair()))
    return wallet, wallet.secret_base58()


# --------------------------------------------------------------------------- helpers


def _parse_json_secret(raw: str) -> bytes:
    try:
        values = json.loads(raw)
    except ValueError:
        raise WalletError("the wallet secret looks like JSON but does not parse") from None
    if (not isinstance(values, list) or len(values) != SECRET_LEN
            or not all(isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 255 for v in values)):
        raise WalletError("a JSON wallet secret must be an array of 64 integers 0-255 (solana-keygen format)")
    return bytes(values)


def _parse_base58_secret(raw: str) -> bytes:
    try:
        decoded = b58decode(raw)
    except ValueError:
        raise WalletError("the wallet secret is neither base58 (Phantom export) nor a JSON byte array") from None
    if len(decoded) != SECRET_LEN:
        raise WalletError(f"the base58 wallet secret decodes to {len(decoded)} bytes; expected 64 "
                          "(paste the full Phantom 'Export Private Key' value, not the address)")
    return decoded


def _secret_encodings(raw: str, secret_bytes: bytes) -> list[str]:
    values = list(secret_bytes)
    return list(dict.fromkeys([raw, b58encode(secret_bytes), json.dumps(values),
                               json.dumps(values, separators=(",", ":"))]))


def _verify_public_half(secret_bytes: bytes) -> None:
    """With ``solders`` installed, refuse a secret whose public half does not match its seed."""
    try:
        solders = require_solders()
    except LiveNotAllowed:  # no solders: the address is taken from the public half as-is
        return
    try:
        solders.keypair.Keypair.from_bytes(secret_bytes)
    except ValueError:
        raise WalletError("the wallet secret is corrupted: its public key does not match its seed") from None


def _decode_transaction(tx_b64: str) -> Any:
    solders = require_solders()
    try:
        return solders.transaction.VersionedTransaction.from_bytes(base64.b64decode(tx_b64, validate=True))
    except (ValueError, TypeError):  # binascii.Error is a ValueError
        raise WalletError("not a base64-encoded Solana VersionedTransaction") from None
