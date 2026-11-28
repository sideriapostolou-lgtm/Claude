"""Family ``dip_rebound``: the engine's own strategy (``strategy.entry_signal``), unchanged.

The only engine-executable family in v1, so the only one that can ever become champion.
"""

from __future__ import annotations

from typing import Any

NAME = "dip_rebound"
PROMOTABLE = True
CONTROL = False


def entry_fn(mint: str, created_ts: float) -> Any:
    """None: the backtester's default entry, :func:`nightcrawler.strategy.entry_signal`."""
    return None
