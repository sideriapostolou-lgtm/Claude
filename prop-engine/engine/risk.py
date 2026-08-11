"""Margin + risk engine. This is where the business lives.

Vig is tiered by model uncertainty (rel_sd of the fair probability) and
constraint weirdness:
  Tier A: liquid analog exists, low variance   ->  9% margin, $500 max stake
  Tier B: standard exotic, decent data         -> 13.5%,      $100
  Tier C: thin data / weird constraint         -> 21%,        $25

Hard rules:
  - never post above 98.5% implied
  - cap total exposure per game
  - same-user repeat-prop velocity flag (sharp probing detection)
  - every quote logged for CLV analysis
"""
from __future__ import annotations

import json
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .base import PriceResult
from .odds import MAX_IMPLIED, american

ROOT = Path(__file__).resolve().parent.parent
QUOTE_LOG = ROOT / "data" / "quotes.jsonl"

QUOTE_TTL_SECONDS = 90
MAX_EXPOSURE_PER_GAME = 5000.0
VELOCITY_WINDOW_S = 300
VELOCITY_LIMIT = 5

TIERS = {
    "A": {"margin": 1.09, "max_stake": 500.0},
    "B": {"margin": 1.135, "max_stake": 100.0},
    "C": {"margin": 1.21, "max_stake": 25.0},
}


@dataclass
class Quote:
    prop_id: str
    quote_id: str
    fair_prob: float
    book_prob: float
    book_odds: str
    tier: str
    max_stake: float
    expires_at: float
    flags: list


class RiskEngine:
    def __init__(self, quote_log: Optional[Path] = None):
        self.quote_log = quote_log or QUOTE_LOG
        self._exposure: dict = defaultdict(float)          # gamePk -> $ exposure
        self._user_quotes: dict = defaultdict(list)        # user -> [timestamps]

    def classify_tier(self, spec, price: PriceResult) -> str:
        c = spec.constraints
        weird = (c.distance_yards is not None and (c.tolerance or 1) <= 1) \
            or "extra_innings" in getattr(spec, "flags", []) \
            or price.fair_prob < 0.005
        if weird or price.rel_sd > 0.45:
            return "C"
        # Tier A: markets with a liquid analog (anytime HR, standard K lines)
        liquid_analog = (spec.market_family in ("player_event", "count_event")
                         and c.by_inning is None and price.rel_sd < 0.18)
        if liquid_analog:
            return "A"
        if price.rel_sd < 0.30:
            return "B"
        return "C"

    def quote(self, spec, price: PriceResult, user_id: Optional[str] = None,
              game_pk: Optional[int] = None) -> Quote:
        flags = list(getattr(spec, "flags", []))
        tier = self.classify_tier(spec, price)
        cfg = TIERS[tier]

        book_prob = min(price.fair_prob * cfg["margin"], MAX_IMPLIED)
        max_stake = cfg["max_stake"]

        if game_pk is not None:
            remaining = MAX_EXPOSURE_PER_GAME - self._exposure[game_pk]
            if remaining <= 0:
                flags.append("exposure_cap_reached")
                max_stake = 0.0
            else:
                max_stake = min(max_stake, remaining)

        if user_id:
            now = time.time()
            recent = [t for t in self._user_quotes[user_id] if now - t < VELOCITY_WINDOW_S]
            recent.append(now)
            self._user_quotes[user_id] = recent
            if len(recent) > VELOCITY_LIMIT:
                flags.append("velocity_flag")
                max_stake = min(max_stake, 10.0)

        q = Quote(prop_id=spec.prop_id, quote_id=str(uuid.uuid4()),
                  fair_prob=price.fair_prob, book_prob=book_prob,
                  book_odds=american(book_prob), tier=tier, max_stake=max_stake,
                  expires_at=time.time() + QUOTE_TTL_SECONDS, flags=flags)
        self._log(spec, price, q, user_id, game_pk)
        return q

    def record_bet(self, game_pk: int, potential_payout: float):
        self._exposure[game_pk] += potential_payout

    def _log(self, spec, price: PriceResult, q: Quote, user_id, game_pk):
        rec = {"ts": time.time(), "quote_id": q.quote_id, "prop_id": q.prop_id,
               "user_id": user_id, "game_pk": game_pk,
               "fair_prob": round(q.fair_prob, 5), "book_prob": round(q.book_prob, 5),
               "book_odds": q.book_odds, "tier": q.tier, "max_stake": q.max_stake,
               "rel_sd": round(price.rel_sd, 4), "flags": q.flags,
               "market_family": spec.market_family, "event": spec.event}
        self.quote_log.parent.mkdir(parents=True, exist_ok=True)
        with open(self.quote_log, "a") as f:
            f.write(json.dumps(rec) + "\n")
