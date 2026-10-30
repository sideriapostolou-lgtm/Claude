"""Defensive parsing helpers for upstream JSON (strings for numbers, nulls, odd timestamps).

All helpers return ``None`` (or the given default) instead of raising on
missing / malformed input, so source clients stay robust to API drift.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Iterable, Iterator, Sequence, TypeVar, overload

__all__ = [
    "to_float",
    "to_int",
    "to_bool",
    "parse_ts",
    "get_path",
    "first_not_none",
    "strip_gt_id",
    "chunks",
]

T = TypeVar("T")
_MISSING_STRINGS = {"", "null", "none", "nan", "n/a", "-"}


@overload
def to_float(value: Any, default: float) -> float: ...
@overload
def to_float(value: Any, default: None = None) -> float | None: ...
def to_float(value: Any, default: float | None = None) -> float | None:
    """``"0.0123"`` / ``12`` / ``1.5`` -> float; None, "", "null", NaN, inf, bools -> ``default``."""
    if value is None or isinstance(value, bool):
        return default
    if isinstance(value, str):
        s = value.strip().replace(",", "")
        if s.lower() in _MISSING_STRINGS:
            return default
        try:
            out = float(s)
        except ValueError:
            return default
    elif isinstance(value, (int, float)):
        out = float(value)
    else:
        return default
    return out if math.isfinite(out) else default


@overload
def to_int(value: Any, default: int) -> int: ...
@overload
def to_int(value: Any, default: None = None) -> int | None: ...
def to_int(value: Any, default: int | None = None) -> int | None:
    """Integer from int / integral float / numeric string (big ints exact); else ``default``.

    ``"18298969251"`` -> 18298969251 exactly (no float rounding for digit strings).
    Non-integral floats are truncated toward zero (``"12.9"`` -> 12).
    """
    if value is None or isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        s = value.strip()
        if s.lower() in _MISSING_STRINGS:
            return default
        if s.lstrip("-").isdigit():
            return int(s)
    f = to_float(value)
    return int(f) if f is not None else default


def to_bool(value: Any, default: bool | None = None) -> bool | None:
    """True/False from bools, 1/0, and strings like yes/no/true/false; else ``default``."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return bool(value)
    if isinstance(value, str):
        s = value.strip().lower()
        if s in ("true", "yes", "y", "1", "on"):
            return True
        if s in ("false", "no", "n", "0", "off"):
            return False
    return default


def parse_ts(value: Any) -> float | None:
    """Epoch seconds (float, UTC) from ISO-8601 strings, epoch seconds or epoch milliseconds.

    * ISO: ``"2026-10-08T15:32:10Z"``, ``"...T15:38:11.750362685Z"`` (fractions
      beyond microseconds are truncated), offsets like ``+00:00``; naive = UTC.
    * Numbers (or numeric strings) > 1e11 are treated as milliseconds.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) or (isinstance(value, str) and to_float(value) is not None):
        f = to_float(value)
        if f is None or f <= 0:
            return None
        return f / 1000.0 if f > 1e11 else f
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    if "." in s:
        head, _, rest = s.partition(".")
        frac = ""
        i = 0
        while i < len(rest) and rest[i].isdigit():
            frac += rest[i]
            i += 1
        s = head + "." + (frac[:6] or "0") + rest[i:]
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def get_path(data: Any, path: str | Sequence[Any], default: Any = None) -> Any:
    """Safe nested lookup: ``get_path(d, "data.attributes.price_usd")`` or ``("a", 0, "b")``.

    Integer path parts (or digit strings) index lists. Missing -> ``default``.
    """
    parts: Iterable[Any] = path.split(".") if isinstance(path, str) else path
    cur = data
    for part in parts:
        if isinstance(cur, dict):
            if part in cur:
                cur = cur[part]
            else:
                return default
        elif isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError, TypeError):
                return default
        else:
            return default
        if cur is None:
            return default
    return cur


def first_not_none(*values: T | None) -> T | None:
    """First argument that is not None (or None)."""
    for v in values:
        if v is not None:
            return v
    return None


def strip_gt_id(gt_id: str | None) -> str | None:
    """GeckoTerminal ids look like ``solana_<address>``; return the address part."""
    if not gt_id:
        return None
    prefix, sep, rest = gt_id.partition("_")
    return rest if sep and prefix == "solana" else gt_id


def chunks(seq: Sequence[T], size: int) -> Iterator[list[T]]:
    """Split ``seq`` into lists of at most ``size`` items (DexScreener batches of 30)."""
    if size < 1:
        raise ValueError("size must be >= 1")
    for i in range(0, len(seq), size):
        yield list(seq[i:i + size])
