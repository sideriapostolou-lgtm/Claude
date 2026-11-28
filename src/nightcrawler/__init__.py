"""nightcrawler: an honest, provable Solana memecoin bot.

Paper mode by default. Every decision and fill is appended to a sha256 hash
chain (see :mod:`nightcrawler.hashing` and :mod:`nightcrawler.ledger`) before
any later price is observed, so results cannot be edited in hindsight.

See docs/DESIGN.md for the module map, units conventions and data flow.
"""

__version__ = "0.1.0"

__all__ = ["__version__"]
