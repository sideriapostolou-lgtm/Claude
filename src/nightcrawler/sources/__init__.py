"""External data sources (owner: O1) and the :class:`Sources` bundle passed to O2 modules.

The clients are imported by :func:`build_sources`, not by this package: importing a pure helper such as
``nightcrawler.sources._parse`` (the backtester does) loads no HTTP code, so the learner process stays
without network modules (docs/LEARNING.md S4, ``tests/test_learn_boundary.py``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nightcrawler.http import HttpClient
    from nightcrawler.sources.dexscreener import DexScreenerClient
    from nightcrawler.sources.geckoterminal import GeckoTerminalClient
    from nightcrawler.sources.jupiter import JupiterClient
    from nightcrawler.sources.rugcheck import RugCheckClient
    from nightcrawler.sources.solana_rpc import SolanaRpc

__all__ = ["Sources", "build_sources"]


@dataclass(slots=True)
class Sources:
    """Every upstream client, sharing one rate-limited :class:`HttpClient`.

    Tests may pass fakes for any member (duck typing).
    """

    dexscreener: DexScreenerClient
    gecko: GeckoTerminalClient
    rugcheck: RugCheckClient
    jupiter: JupiterClient
    rpc: SolanaRpc


def build_sources(settings: Any, http: HttpClient) -> Sources:
    """Construct all clients from :class:`~nightcrawler.config.Settings` and one ``HttpClient``."""
    from nightcrawler.sources.dexscreener import DexScreenerClient
    from nightcrawler.sources.geckoterminal import GeckoTerminalClient
    from nightcrawler.sources.jupiter import JupiterClient
    from nightcrawler.sources.rugcheck import RugCheckClient
    from nightcrawler.sources.solana_rpc import SolanaRpc

    return Sources(
        dexscreener=DexScreenerClient(http),
        gecko=GeckoTerminalClient(http),
        rugcheck=RugCheckClient(http),
        jupiter=JupiterClient(http, base_url=settings.jupiter_base_url, api_key=settings.jupiter_api_key),
        rpc=SolanaRpc(http, url=settings.solana_rpc_url),
    )
