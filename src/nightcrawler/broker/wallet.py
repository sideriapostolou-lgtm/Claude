"""Bot wallet keypair handling (owner: O5). The secret NEVER appears in logs, repr or errors.

Accepted secret formats (``BOT_WALLET_SECRET``):

* base58 string of a 64-byte secret key (Phantom "Export Private Key");
* JSON array of 64 ints 0-255 (``solana-keygen`` file contents).

Byte layout: ``secret[0:32]`` = ed25519 seed, ``secret[32:64]`` = public key,
so the address can be derived WITHOUT ``solders`` (``wallet show`` works
without the live extra). When ``solders`` is installed, ``load_keypair``
also verifies the public half matches the seed.

On load, register BOTH encodings of the secret with the logging redaction
filter (``logging_setup.RedactionFilter.add_secret``) when one is given.
"""

from __future__ import annotations

from typing import Any

from nightcrawler.config import Secret

__all__ = ["WalletError", "Wallet", "load_keypair", "generate_new", "PHANTOM_IMPORT_HELP"]

PHANTOM_IMPORT_HELP = (
    "To view this wallet in Phantom: Settings -> Manage Accounts -> Add / Connect Wallet -> "
    "Import Private Key, then paste the secret. Use this wallet ONLY for the bot and fund it "
    "with no more than you can lose."
)


class WalletError(ValueError):
    """Bad secret format. The message never contains the secret."""


class Wallet:
    """A loaded bot keypair. ``repr``/``str`` show only the public address."""

    def __init__(self, secret_bytes: bytes) -> None:
        """``secret_bytes``: exactly 64 bytes (seed + pubkey). Raises ``WalletError`` otherwise."""
        raise NotImplementedError

    def pubkey(self) -> str:
        """Base58 public address."""
        raise NotImplementedError

    def keypair(self) -> Any:
        """``solders.keypair.Keypair`` (requires the ``live`` extra; raises ``LiveNotAllowed`` otherwise)."""
        raise NotImplementedError

    def sign_transaction_b64(self, tx_b64: str) -> str:
        """Deserialize an unsigned Ultra ``VersionedTransaction`` (base64), sign it, return base64."""
        raise NotImplementedError

    def secret_base58(self) -> str:
        """The secret in Phantom (base58) format. ONLY for the ``wallet new`` command output."""
        raise NotImplementedError

    def __repr__(self) -> str:
        raise NotImplementedError


def load_keypair(secret: str | Secret, redaction_filter: Any | None = None) -> Wallet:
    """Parse a base58 or JSON-array secret into a :class:`Wallet`.

    Whitespace is stripped. Raises :class:`WalletError` (message without the
    secret) on wrong length/format or a pubkey/seed mismatch.
    """
    raise NotImplementedError


def generate_new() -> tuple[Wallet, str]:
    """Create a fresh random keypair with ``solders.keypair.Keypair()`` (needs the ``live``
    extra; raises ``LiveNotAllowed`` with install instructions otherwise).
    Returns ``(wallet, secret_base58)``.

    The CLI prints the address and the secret ONCE with a big warning and
    :data:`PHANTOM_IMPORT_HELP`; nothing is written to disk or logs.
    """
    raise NotImplementedError
