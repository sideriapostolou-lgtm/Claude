"""Parser package: utterance -> validated PropSpec."""
from __future__ import annotations

import os
from typing import Optional

from .propspec import ParseResult, PropSpec  # noqa: F401
from .rule_parser import parse_with_rules
from .validate import ValidationContext, fetch_context, validate  # noqa: F401


def _has_anthropic_credentials() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def parse(utterance: str, ctx: Optional[ValidationContext] = None,
          use_llm: Optional[bool] = None) -> ParseResult:
    """Parse an utterance and apply deterministic validation.

    use_llm=None auto-detects Anthropic credentials; the rule parser is the
    fallback so the system works without an API key.
    """
    if use_llm is None:
        use_llm = _has_anthropic_credentials()
    if use_llm:
        try:
            from .llm_parser import parse_with_llm
            result = parse_with_llm(utterance)
        except Exception:
            result = parse_with_rules(utterance)
    else:
        result = parse_with_rules(utterance)
    return validate(result, ctx)
