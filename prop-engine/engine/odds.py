"""Odds math shared across the engine."""
from __future__ import annotations

MAX_IMPLIED = 0.985  # never post a price above 98.5% implied


def american(p: float) -> str:
    p = min(max(p, 0.001), MAX_IMPLIED)
    if p >= 0.5:
        return f"-{round(100 * p / (1 - p))}"
    return f"+{round(100 * (1 - p) / p)}"


def implied_from_american(odds: str) -> float:
    v = int(odds)
    if v < 0:
        return -v / (-v + 100)
    return 100 / (v + 100)
