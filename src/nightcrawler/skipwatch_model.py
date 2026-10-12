"""Causal observations of a public wallet; no order or account capability.

Observed inventory is only the public fills collected by this watcher. The
Coinbase fair-value proxy is explanatory, not the market settlement oracle.
"""

from __future__ import annotations

import math
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any

from .speeddesk_model import fair_up


@dataclass(frozen=True)
class Observation:
    kind: str
    payload: dict[str, Any]
    at: float


class SkipwatchModel:
    def __init__(self, started_at: float, *, poll_s: float = 2.5) -> None:
        self.started_at, self.poll_s = started_at, poll_s
        self.markets: dict[str, dict[str, Any]] = {}
        self.tokens: dict[str, tuple[str, str]] = {}
        self.books: dict[str, dict[str, dict[float, float]]] = {}
        self.book_ready: set[str] = set()
        self.book_history: dict[str, deque[dict[str, Any]]] = defaultdict(lambda: deque(maxlen=20_000))
        self.btc: deque[tuple[float, float, float]] = deque(maxlen=100_000)
        self.seconds: dict[int, tuple[float, float]] = {}
        self.health: dict[str, dict[str, Any]] = {}
        self.trades: deque[dict[str, Any]] = deque(maxlen=20_000)
        self.seen_fills: set[str] = set()
        self.pending: dict[str, dict[str, Any]] = {}
        self.inventory: dict[str, dict[str, float]] = defaultdict(lambda: {"up": 0.0, "down": 0.0})
        self.counts: dict[str, dict[str, Any]] = defaultdict(dict)
        self.match_counts = {"inferred": 0, "ambiguous": 0, "unmatched": 0}
        self.last_opportunity: int | None = None
        self.wallet_watermark: float | None = None
        self.last_wallet_at: float | None = None
        self.last_event_at: float | None = None
        self.gaps = 0
        self.completed: dict[str, int] = {}
        self.observed_windows: set[str] = set()

    def ingest(self, kind: str, data: dict[str, Any], observed_at: float) -> bool:
        """Apply one recorded event. False identifies an already journaled fill."""
        self.last_event_at = observed_at
        if kind == "market":
            window = str(data["market_id"])
            self.markets[window] = dict(data)
            for side in ("up", "down"):
                token = data.get(f"{side}_token")
                if token:
                    self.tokens[str(token)] = (window, side)
        elif kind == "book_deltas":
            for update in data["updates"]:
                self.ingest("book_delta", {**data, **update}, observed_at)
            return True
        elif kind in {"book_snapshot", "book_delta"}:
            token = str(data["token_id"])
            levels = self.books.setdefault(token, {"bids": {}, "asks": {}})
            if kind == "book_snapshot":
                for side in ("bids", "asks"):
                    levels[side] = {float(price): float(size) for price, size in data.get(side, []) if float(size) > 0}
                if data.get("valid", True) is True:
                    self.book_ready.add(token)
            else:
                for item in data.get("changes", []):
                    side = "bids" if item["book_side"] == "bid" else "asks"
                    price, size = float(item["price"]), float(item["size"])
                    if size > 0:
                        levels[side][price] = size
                    else:
                        levels[side].pop(price, None)
            if data.get("valid", True) is not True:
                self.book_ready.discard(token)
            at = float(data.get("exchange_at", observed_at))
            top = {side: sorted(levels[side].items(), reverse=side == "bids")[:5] for side in ("bids", "asks")}
            self.book_history[token].append({"at": at, "observed_at": observed_at, **top,
                                              "valid": token in self.book_ready and data.get("valid", True) is True})
        elif kind == "bitcoin_tick":
            at, price = float(data["exchange_at"]), float(data["price"])
            if price > 0 and at <= observed_at + 1:
                self.btc.append((at, observed_at, price))
                second = int(at)
                prior = self.seconds.get(second)
                if prior is None or observed_at >= prior[1]:
                    self.seconds[second] = (price, observed_at)
                cutoff = int(observed_at) - 3720
                self.seconds = {stamp: value for stamp, value in self.seconds.items() if stamp >= cutoff}
        elif kind == "health":
            source = str(data["source"])
            self.health[source] = {**data, "observed_at": observed_at}
            if source == "wallet" and data.get("status") == "connected":
                watermark = data.get("wallet_watermark")
                if isinstance(watermark, (int, float)) and math.isfinite(watermark):
                    self.wallet_watermark = max(self.wallet_watermark or float(watermark), float(watermark))
            if data.get("status") != "connected":
                self.gaps += 1
                if source in {"clob", "book", "trades"}:
                    self._invalidate_books(observed_at)
        elif kind == "public_trade":
            self.trades.append({**data, "observed_at": observed_at})
        elif kind == "wallet_fill":
            identity = str(data["fill_id"])
            if identity in self.seen_fills:
                return False
            self.seen_fills.add(identity)
            if len(self.seen_fills) > 200_000 or len(self.pending) > 10_000:
                raise ValueError("Public wallet observation memory limit reached")
            at = float(data.get("exchange_at", data.get("at", observed_at)))
            window = str(data.get("market_id", data.get("window", "")))
            side = str(data.get("side", "unknown"))
            item = {**data, "at": at, "observed_at": observed_at, "window": window}
            self.pending[identity] = item
            if side in {"up", "down"}:
                delta = float(data["size"]) * (1 if str(data.get("action", "buy")).lower() == "buy" else -1)
                self.inventory[window][side] += delta
            counts = self.counts[window]
            counts["wallet_fills"] = counts.get("wallet_fills", 0) + 1
            counts["observed_volume"] = counts.get("observed_volume", 0.0) + float(data["size"])
            counts["last_fill_at"] = at
            self.last_wallet_at = observed_at
        elif kind == "wallet_observation":
            self.pending.pop(str(data["fill_id"]), None)
            confidence = str(data["confidence"])
            self.match_counts[confidence] += 1
        elif kind == "window_summary":
            self.completed[str(data["window"])] = int(data["wallet_fills"])
        elif kind == "gap":
            self.gaps += 1
            self.health.clear()
            self._invalidate_books(observed_at)
        elif kind == "opportunity":
            self.observed_windows.add(str(data["window"]))
        self._prune(observed_at)
        return True

    def _invalidate_books(self, observed_at: float) -> None:
        self.book_ready.clear()
        self.books.clear()
        for history in self.book_history.values():
            if history:
                history.append({**history[-1], "valid": False, "observed_at": observed_at, "at": observed_at})

    def _prune(self, now: float) -> None:
        # Delayed wallet receipts need historical context. Both age and count
        # bound memory; missing history is reported as missing coverage.
        for history in self.book_history.values():
            while history and history[0]["observed_at"] < now - 120:
                history.popleft()
        while self.btc and self.btc[0][1] < now - 3720:
            self.btc.popleft()
        while self.trades and self.trades[0]["observed_at"] < now - 120:
            self.trades.popleft()
        expired = [key for key, market in self.markets.items() if float(market["end"]) < now - 3600]
        for window in expired:
            market = self.markets.pop(window)
            for side in ("up", "down"):
                token = str(market.get(f"{side}_token", ""))
                self.tokens.pop(token, None)
                self.books.pop(token, None)
                self.book_history.pop(token, None)
                self.book_ready.discard(token)

    def _btc_before(self, at: float) -> tuple[float, float, float] | None:
        return next((tick for tick in reversed(self.btc) if tick[0] <= at and tick[1] <= at), None)

    def _book_before(self, token: str, at: float) -> dict[str, Any] | None:
        return next((book for book in reversed(self.book_history.get(token, ()))
                     if book["at"] <= at and book["observed_at"] <= at), None)

    def coverage(self, now: float, token: str | None = None) -> dict[str, Any]:
        wallet = self.health.get("wallet", {})
        watermark = wallet.get("wallet_watermark")
        fresh_wallet = (wallet.get("status") == "connected" and isinstance(watermark, (int, float))
                        and 0 <= now - float(wallet["observed_at"]) <= self.poll_s + 3
                        and 0 <= now - float(watermark) <= self.poll_s + 4)
        tick = self._btc_before(now)
        book = self._book_before(token, now) if token else None
        clob = self.health.get("clob", self.health.get("trades", {}))
        return {"bitcoin": tick is not None and 0 <= now - tick[0] <= 3 and now - tick[1] <= 3,
                "book": bool(book and book["valid"] and 0 <= now - book["at"] <= 3
                             and 0 <= now - book["observed_at"] <= 3),
                "wallet": bool(fresh_wallet), "wallet_watermark": watermark,
                "trades": clob.get("status") == "connected" and clob.get("observed_at", math.inf) <= now}

    def features(self, window: str, side: str, at: float) -> dict[str, Any]:
        market = self.markets.get(window, {})
        token = str(market.get(f"{side}_token", ""))
        tick = self._btc_before(at)
        book = self._book_before(token, at)
        start, end = market.get("start"), market.get("end")
        opening_tick = self._btc_before(float(start)) if start is not None else None
        if opening_tick is not None and start is not None and float(start) - opening_tick[0] > 3:
            opening_tick = None
        prices = {stamp: price for stamp, (price, seen) in self.seconds.items() if int(at) - 3600 <= stamp < int(at) and seen <= at}
        returns = [math.log(prices[stamp] / prices[stamp - 1]) for stamp in prices if stamp - 1 in prices]
        sigma = math.sqrt(sum(value * value for value in returns) / len(returns)) if len(returns) >= 300 else None
        opening = opening_tick[2] if opening_tick else None
        fair = fair_up(tick[2], opening, sigma, max(0, float(end) - at)) if (
            tick and opening is not None and sigma is not None and end is not None) else None
        inventory = self.inventory.get(window, {"up": 0.0, "down": 0.0})
        total = abs(inventory["up"]) + abs(inventory["down"])
        features: dict[str, Any] = {"at": at, "observed_at": at, "window": window, "market_id": window,
                                   "slug": market.get("slug"), "window_start": start, "window_end": end,
                                   "side": side, "btc_price": tick[2] if tick else None, "opening_price": opening,
                                   "opening_method": "latest Coinbase tick known at window start, at most 3s old",
                                   "opening_age_s": float(start) - opening_tick[0] if opening_tick and start is not None else None,
                                   "sigma": sigma, "fair": fair if side == "up" or fair is None else 1 - fair,
                                   "sigma_method": "RMS of at least 300 actually observed adjacent one-second returns",
                                   "seconds_left": max(0, float(end) - at) if end is not None else None,
                                   "prior_up": inventory["up"], "prior_down": inventory["down"],
                                   "imbalance": (inventory["up"] - inventory["down"]) / total if total else 0.0,
                                   "inventory_scope": "public fills observed by this process; not account positions",
                                   "fair_source": "Coinbase normal-CDF proxy; not settlement oracle",
                                   "coverage": self.coverage(at, token)}
        for seconds in (1, 5, 30):
            prior = self._btc_before(at - seconds)
            features[f"move_{seconds}s"] = math.log(tick[2] / prior[2]) if (
                tick and prior and at - seconds - prior[0] <= 3) else None
        for key, levels_key in (("bid", "bids"), ("ask", "asks")):
            levels = book[levels_key] if book and book["valid"] else []
            features[key] = levels[0][0] if levels else None
            features[f"{key}_depth"] = sum(size for _, size in levels) if levels else None
            features[f"{key}_top_size"] = levels[0][1] if levels else None
        features["depth_scope"] = "best five displayed price levels"
        return features

    def due(self, now: float) -> list[Observation]:
        events: list[Observation] = []
        for identity, fill in list(self.pending.items()):
            if now - fill["observed_at"] < 5:
                continue
            at = float(fill["at"])
            candidates = [trade for trade in self.trades
                          if trade.get("token_id") == fill.get("token_id")
                          and abs(float(trade["exchange_at"]) - at) <= 1
                          and abs(float(trade["price"]) - float(fill["price"])) <= 1e-6
                          and abs(float(trade["size"]) - float(fill["size"])) <= 1e-6
                          and (not trade.get("transaction_hash") or not fill.get("transaction_hash")
                               or trade["transaction_hash"] == fill["transaction_hash"])]
            confidence = "inferred" if len(candidates) == 1 else "ambiguous" if candidates else "unmatched"
            # These historical observations are descriptive. The fitter uses
            # prospective opportunity records, never a fill's price or size.
            payload = {**self.features(fill["window"], str(fill.get("side", "unknown")), at),
                       "fill_id": identity, "wallet_observed_at": fill["observed_at"],
                       "price": fill["price"], "size": fill["size"], "action": fill.get("action"),
                       "confidence": confidence, "candidate_prints": len(candidates),
                       "candidate_evidence": [{"trade_id": item.get("trade_id"), "at": item["exchange_at"],
                                               "observed_at": item["observed_at"], "price": item["price"],
                                               "size": item["size"]} for item in candidates[:10]],
                       "maker_taker": "unknown", "cancellations": "unobservable",
                       "matching_precision": "price/size and public one-second timestamps; identity is not proven",
                       "context_scope": "causal history retained for at most 120s / 20000 book updates per token; missing coverage remains unknown"}
            # The observation itself must not claim pre-fill inventory: our
            # current inventory includes delayed public fills learned afterward.
            for key in ("prior_up", "prior_down", "imbalance"):
                payload[key] = None
            events.append(Observation("wallet_observation", payload, at))
        if self.last_opportunity != int(now):
            self.last_opportunity = int(now)
            coverage = {"at": now, "observed_at": now, **self.coverage(now)}
            events.append(Observation("coverage", coverage, now))
            for window, market in self.markets.items():
                if float(market["start"]) <= now < float(market["end"]):
                    for side in ("up", "down"):
                        events.append(Observation("opportunity", self.features(window, side, now), now))
        for window, market in self.markets.items():
            count = self.counts.get(window, {}).get("wallet_fills", 0)
            if now >= float(market["end"]) + 30 and self.completed.get(window) != count:
                payload = {"window": window, "slug": market.get("slug"), "window_start": market["start"],
                           "window_end": market["end"], "wallet_fills": count,
                           "observed_volume": self.counts.get(window, {}).get("observed_volume", 0.0),
                           "observed_up": self.inventory[window]["up"], "observed_down": self.inventory[window]["down"],
                           "cancellations": "unobservable", "revision": window in self.completed,
                           "coverage_complete": False, "limitation": "public observations, not exact order history"}
                events.append(Observation("window_summary", payload, now))
        return events
