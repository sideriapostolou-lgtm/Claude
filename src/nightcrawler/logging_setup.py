"""Logging: one line per event, secrets redacted everywhere.

Call :func:`setup_logging` once at process start (the CLI does it) with
``settings.secret_values()``. The :class:`RedactionFilter` sits on the HANDLER,
so every record that reaches the output - from any logger, including
tracebacks - is scrubbed of:

* the exact secret values passed in (wallet secret, API keys, RPC api-key),
* a JSON array of 64 small integers (solana-keygen secret format),
* Anthropic-style keys (``sk-ant-...``).

Streams: DEBUG/INFO go to **stdout** and WARNING+ to **stderr** (Railway, like
most log collectors, labels every stderr line "error"). Both handlers share the
one redaction filter. Pass ``stream=`` to send every level to a single stream
instead (tests, and commands whose stdout carries data such as ``--json``).

Module loggers: ``log = get_logger(__name__)`` -> ``nightcrawler.<module>``.
Message style: ``"event key=value key=value"`` (one line; newlines are escaped).
"""

from __future__ import annotations

import logging
import re
import sys
import time
from typing import IO, Iterable

__all__ = ["REDACTED", "RedactionFilter", "OneLineFormatter", "setup_logging", "get_logger", "redact_text"]

REDACTED = "[REDACTED]"
# NOTE: base58 64-byte secrets are NOT pattern-matched because transaction
# signatures have the same shape and must stay visible. Exact secret values
# (both encodings - wallet.py registers the base58 form) are redacted instead.
_PATTERNS = [
    re.compile(r"\[\s*(?:\d{1,3}\s*,\s*){63}\d{1,3}\s*\]"),  # JSON byte-array secret (64 ints)
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{8,}"),  # Anthropic keys
]


def redact_text(text: str, secrets: Iterable[str] = ()) -> str:
    """Return ``text`` with secrets and secret-shaped strings replaced by ``[REDACTED]``."""
    for s in sorted({s for s in secrets if s and len(s) >= 6}, key=len, reverse=True):
        text = text.replace(s, REDACTED)
    for pat in _PATTERNS:
        text = pat.sub(REDACTED, text)
    return text


class RedactionFilter(logging.Filter):
    """Scrubs the formatted message and any exception text of a record."""

    def __init__(self, secrets: Iterable[str] = ()) -> None:
        super().__init__()
        self.secrets = [s for s in secrets if s]

    def add_secret(self, value: str) -> None:
        if value:
            self.secrets.append(value)

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:  # pragma: no cover - malformed format args
            msg = str(record.msg)
        record.msg = redact_text(msg, self.secrets)
        record.args = None
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = redact_text(record.exc_text, self.secrets)
        if record.stack_info:
            record.stack_info = redact_text(record.stack_info, self.secrets)
        return True


class OneLineFormatter(logging.Formatter):
    """``2026-10-08T16:00:00Z INFO nightcrawler.engine: message`` - newlines escaped."""

    converter = time.gmtime  # type: ignore[assignment]

    def __init__(self) -> None:
        super().__init__("%(asctime)s %(levelname)s %(name)s: %(message)s", datefmt="%Y-%m-%dT%H:%M:%SZ")

    def format(self, record: logging.LogRecord) -> str:
        text = super().format(record)
        return text.replace("\r", "").replace("\n", " | ")


class _BelowLevel(logging.Filter):
    """Passes only records below ``level`` (keeps WARNING+ off the stdout handler)."""

    def __init__(self, level: int) -> None:
        super().__init__()
        self.level = level

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno < self.level


def setup_logging(level: str = "INFO", secrets: Iterable[str] = (), stream: IO[str] | None = None) -> RedactionFilter:
    """Configure the root logger with redacting stream handlers (idempotent).

    Without ``stream``: DEBUG/INFO -> ``sys.stdout``, WARNING+ -> ``sys.stderr``.
    With ``stream``: every level -> that one stream.
    Returns the (shared) filter so callers can ``add_secret`` later (e.g. a freshly
    generated wallet secret). Third-party chatty loggers are capped at WARNING.
    """
    root = logging.getLogger()
    for h in list(root.handlers):
        if getattr(h, "_nightcrawler", False):
            root.removeHandler(h)
    filt = RedactionFilter(secrets)
    if stream is not None:
        root.addHandler(_handler(stream, filt))
    else:
        root.addHandler(_handler(sys.stdout, filt, below=logging.WARNING))
        root.addHandler(_handler(sys.stderr, filt, level=logging.WARNING))
    root.setLevel(getattr(logging, str(level).upper(), logging.INFO))
    for noisy in ("urllib3", "httpx", "httpcore", "anthropic"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    return filt


def _handler(stream: IO[str], filt: RedactionFilter, *, level: int = logging.NOTSET,
             below: int | None = None) -> logging.Handler:
    handler = logging.StreamHandler(stream)
    handler._nightcrawler = True  # type: ignore[attr-defined]
    handler.setLevel(level)
    if below is not None:
        handler.addFilter(_BelowLevel(below))
    handler.addFilter(filt)
    handler.setFormatter(OneLineFormatter())
    return handler


def get_logger(name: str) -> logging.Logger:
    """``get_logger(__name__)`` -> a ``nightcrawler.*`` logger."""
    if not name.startswith("nightcrawler"):
        name = f"nightcrawler.{name}"
    return logging.getLogger(name)
