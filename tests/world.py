"""A fake but self-consistent Solana memecoin market behind FakeHttp (engine + CLI tests).

Every upstream endpoint the engine touches (Jupiter tokens/price/Ultra order,
GeckoTerminal pools/ohlcv/trades, DexScreener, RugCheck, Solana RPC, Shield)
is served from one small mutable state, so tests can move the price and walk
a whole trade tick by tick. ``GARY`` passes the cocoon (``rugcheck_report.json``),
``RISKY`` fails it (``rugcheck_report_risky.json``).
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Any

from fakes import FakeClock, FakeHttp, FakeRequest
from nightcrawler.clock import iso_utc
from nightcrawler.models import SOL_MINT, Candle

GARY = "8ZCmwpW3MtC5UpNcZf7U4HMvRNTo71syU11BDiAFpump"  # rugcheck_report.json: passes the cocoon
GARY_POOL = "2uZuTQEjcXcR1ESwMdGTpqEwM5PCekEwrSNVRPc1EhS1"  # its PumpSwap pool (LP 100 % locked)
GARY_DEV = "G7YaEzm4c1aMQcn1SQLUPHYnoUNE7bG4XwQ4nxyYydn"
RISKY = "EDQRk4ETkyb4qkcGfeVMxK3FsFXava7Q3HFxmpJXpump"  # rugcheck_report_risky.json: fails
RISKY_POOL = "EA2y1S4Up5KerH2Vn2arxcwsGt84R38KQEyb3a3UbG5y"
SUPPLY = 1_000_000_000  # whole tokens -> mcap = price * 1e9
DECIMALS = 6
SOL_USD = 100.0
SWAP_COST = 0.012  # pool + platform fee + impact the fake Ultra charges per side


def iso(ts: float) -> str:
    return iso_utc(ts) or ""


def dip_rebound_candles(now: float) -> list[Candle]:
    """120 closed 1m candles: pump to $1.0e-3, dump 60 % to $0.40e-3, two green breakout candles."""
    start = int(now) - 120 * 60
    out: list[Candle] = []
    for i in range(120):
        ts = start + i * 60
        if i < 40:  # pump
            o = 0.5e-3 + i * 0.0125e-3
            c = o + 0.0125e-3
            out.append(Candle(ts, o, c * 1.001, o * 0.999, c, 2000.0))
        elif i < 100:  # dump to the low
            o = 1.0e-3 - (i - 40) * 0.01e-3
            c = o - 0.01e-3
            out.append(Candle(ts, o, o * 1.001, c * 0.999 if i < 99 else 0.40e-3, c, 800.0))
        elif i < 118:  # base
            o, c = 0.41e-3, (0.405e-3 if i % 2 else 0.412e-3)
            out.append(Candle(ts, o, 0.414e-3, 0.403e-3, c, 300.0))
        elif i == 118:  # buyers return
            out.append(Candle(ts, 0.41e-3, 0.435e-3, 0.405e-3, 0.43e-3, 500.0))
        else:  # breakout close above the previous high, rising volume
            out.append(Candle(ts, 0.43e-3, 0.465e-3, 0.428e-3, 0.46e-3, 900.0))
    return out


def jupiter_token(mint: str, symbol: str, pool: str, created: float, price: float, dev: str,
                  dev_mints: int = 1, graduated: float | None = None) -> dict[str, Any]:
    """A graduated pump.fun coin as Jupiter tokens/v2 lists it: ``graduatedPool`` comes with ``graduatedAt``
    (``graduated``; default: at creation, an instant graduate like the real GARY)."""
    return {"id": mint, "name": symbol, "symbol": symbol, "decimals": DECIMALS, "dev": dev,
            "graduatedPool": pool, "graduatedAt": iso(created if graduated is None else graduated),
            "firstPool": {"id": pool, "createdAt": iso(created)},
            "mcap": price * SUPPLY, "fdv": price * SUPPLY, "liquidity": 80_000.0, "usdPrice": price,
            "holderCount": 3000, "launchpad": "pump.fun", "twitter": "https://x.com/example",
            "audit": {"isSus": False, "mintAuthorityDisabled": True, "freezeAuthorityDisabled": True,
                      "devMints": dev_mints}}


@dataclass
class World:
    """Mutable market state behind every fake upstream endpoint."""

    http: FakeHttp
    clock: FakeClock
    price: float = 0.46e-3
    liquidity: float = 80_000.0
    buys_m5: int = 30
    sells_m5: int = 10
    candles: list[Candle] = field(default_factory=list)
    trending: list[dict[str, Any]] = field(default_factory=list)
    trades: list[dict[str, Any]] = field(default_factory=list)
    ids: Any = field(default_factory=lambda: itertools.count(1))

    # ---------------------------------------------------------------- responders
    def pair(self, mint: str) -> dict[str, Any]:
        return {"chainId": "solana", "dexId": "pumpswap", "pairAddress": GARY_POOL,
                "baseToken": {"address": mint, "name": "Gary", "symbol": "Gary"},
                "quoteToken": {"address": SOL_MINT, "symbol": "SOL"},
                "priceUsd": str(self.price), "marketCap": self.price * SUPPLY, "fdv": self.price * SUPPLY,
                "liquidity": {"usd": self.liquidity},
                "txns": {"m5": {"buys": self.buys_m5, "sells": self.sells_m5}, "h1": {"buys": 300, "sells": 200}},
                "volume": {"m5": 5000.0, "h1": 60000.0}, "priceChange": {"m5": 3.0, "h1": -20.0}}

    def dexscreener_tokens(self, req: FakeRequest) -> list[dict[str, Any]]:
        mints = req.url.rsplit("/", 1)[-1].split(",")
        return [self.pair(m) for m in mints if m == GARY]

    def ohlcv(self, req: FakeRequest) -> dict[str, Any]:
        params = req.params or {}
        before = int(params.get("before_timestamp", 1 << 62))
        limit = int(params.get("limit", 1000))
        rows = [c.to_row() for c in self.candles if c.ts < before][-limit:]
        return {"data": {"attributes": {"ohlcv_list": list(reversed(rows))}}}

    def prices(self, req: FakeRequest) -> dict[str, Any]:
        ids = (req.params or {}).get("ids", "").split(",")
        table = {SOL_MINT: SOL_USD, GARY: self.price}
        return {m: {"usdPrice": table[m], "decimals": 9 if m == SOL_MINT else DECIMALS} for m in ids if m in table}

    def order(self, req: FakeRequest) -> dict[str, Any]:
        p = req.params or {}
        amount = int(p["amount"])
        if p["inputMint"] == SOL_MINT:  # buy: lamports -> tokens
            usd = amount / 1e9 * SOL_USD
            out = int(usd * (1 - SWAP_COST) / self.price * 10**DECIMALS)
            out_usd = usd * (1 - SWAP_COST)
        else:  # sell: tokens -> lamports
            usd = amount / 10**DECIMALS * self.price
            out_usd = usd * (1 - SWAP_COST)
            out = int(out_usd / SOL_USD * 1e9)
        return {"inputMint": p["inputMint"], "outputMint": p["outputMint"], "inAmount": str(amount),
                "outAmount": str(out), "otherAmountThreshold": str(out), "slippageBps": 0,
                "priceImpactPct": "-0.002", "feeBps": 10, "routePlan": [{"swapInfo": {"label": "Pump.fun Amm"}}],
                "transaction": None, "requestId": f"req-{next(self.ids)}", "inUsdValue": usd,
                "outUsdValue": out_usd, "signatureFeeLamports": 0, "prioritizationFeeLamports": 0,
                "rentFeeLamports": 0, "router": "metis"}

    def install(self) -> None:
        h = self.http
        h.register("/tokens/v2/recent", [])
        h.register("/tokens/v2/toptrending/1h", lambda _r: self.trending)
        h.register("/new_pools", {"data": [], "included": []})
        h.register("/token-boosts/latest/v1", [])
        h.register("/token-profiles/latest/v1", [])
        h.register_fixture(f"/tokens/{GARY}/report", "rugcheck_report")
        h.register_fixture(f"/tokens/{RISKY}/report", "rugcheck_report_risky")
        h.register_fixture("api.mainnet-beta.solana.com", "rpc_getAccountInfo_mint", method="POST")
        h.register("/ultra/v1/shield", {"warnings": {}})
        h.register("/tokens/v1/solana/", self.dexscreener_tokens)
        h.register("/ohlcv/minute", self.ohlcv)
        h.register("/trades", lambda _r: {"data": self.trades})
        h.register("/price/v3", self.prices)
        h.register("/ultra/v1/order", self.order)




def make_world(http: FakeHttp, clock: FakeClock) -> World:
    """A World with GARY and RISKY trending and the dip-rebound candles ending now."""
    now = clock.now()
    w = World(http=http, clock=clock, candles=dip_rebound_candles(now))
    w.trending = [jupiter_token(GARY, "Gary", GARY_POOL, now - 5 * 3600, w.price, GARY_DEV),
                  jupiter_token(RISKY, "RISKY", RISKY_POOL, now - 3 * 3600, w.price, "Dev1111111111111111111111")]
    w.install()
    return w
