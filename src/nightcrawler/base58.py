"""Minimal Bitcoin-alphabet base58 (Solana addresses, Phantom secret keys).

Dependency-free so address validation and ``wallet show`` work without the
optional ``solders`` package.
"""

from __future__ import annotations

__all__ = ["ALPHABET", "b58encode", "b58decode", "is_pubkey"]

ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_INDEX = {c: i for i, c in enumerate(ALPHABET)}


def b58encode(data: bytes) -> str:
    """Encode bytes to base58 (leading zero bytes become leading '1's)."""
    n = int.from_bytes(data, "big")
    out = []
    while n:
        n, r = divmod(n, 58)
        out.append(ALPHABET[r])
    pad = len(data) - len(data.lstrip(b"\0"))
    return "1" * pad + "".join(reversed(out))


def b58decode(text: str) -> bytes:
    """Decode base58 text. Raises ``ValueError`` on invalid characters."""
    text = text.strip()
    n = 0
    for ch in text:
        try:
            n = n * 58 + _INDEX[ch]
        except KeyError:
            raise ValueError("invalid base58 character") from None
    body = n.to_bytes((n.bit_length() + 7) // 8, "big") if n else b""
    pad = len(text) - len(text.lstrip("1"))
    return b"\0" * pad + body


def is_pubkey(text: object) -> bool:
    """True if ``text`` is a base58 string decoding to exactly 32 bytes."""
    if not isinstance(text, str) or not (32 <= len(text) <= 44):
        return False
    try:
        return len(b58decode(text)) == 32
    except ValueError:
        return False
