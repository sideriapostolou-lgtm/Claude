"""Family A's universe, exclusions, tick grid and risk clusters (PROTOCOL.md sections 4.1, 4.3, 4.4, 5.2).

Pure functions over raw Kalshi rows, in exact decimals. The recorder calls ``admit`` with its wider
recording window (5 h - 8 d left) and without the fee rule, so every market is on tape before it can
enter the protocol window; the replay calls it with the protocol's 6 h - 7 d window and the fee rule.
Every exclusion is counted against the first rule that fails, in the protocol's order.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from itertools import pairwise
from typing import Any
from zoneinfo import ZoneInfo

OPEN_CATEGORIES = ("Crypto", "Climate and Weather", "Commodities", "Financials")
# Washington blocks these for the owner's account (PROTOCOL.md U1); every other category is unconfirmed.
BLOCKED_CATEGORIES = frozenset({"Sports", "Elections", "Politics", "Entertainment", "Culture",
                                "Science and Technology", "Tech & Science", "Mentions"})
PROTOCOL_WINDOW = (6 * 3600.0, 7 * 86400.0)
RECORDER_WINDOW = (5 * 3600.0, 8 * 86400.0)
FEE_FRESH_S = 26 * 3600.0
MIN_DURATION_S = 24 * 3600.0
NEW_YORK = ZoneInfo("America/New_York")
ONE = Decimal(1)
ZERO = Decimal(0)
RULES = ("U1", "U2", "U3", "U4", "U5", "U6", "U7", "U8", "U9", "U10", "U11")
_MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")


def dec(value: Any) -> Decimal | None:
    """An exact decimal from Kalshi's decimal strings (or ints); floats, bools and junk are refused."""
    if isinstance(value, (bool, float)):
        return None
    if isinstance(value, int):
        return Decimal(value)
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        out = Decimal(value.strip())
    except InvalidOperation:
        return None
    return out if out.is_finite() else None


def ts(value: Any) -> float | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed.timestamp() if parsed.tzinfo is not None else None


# --------------------------------------------------------------------------- tick grid (U11, section 5.2)
@dataclass(frozen=True)
class Band:
    start: Decimal
    end: Decimal
    step: Decimal


@dataclass(frozen=True)
class TickGrid:
    bands: tuple[Band, ...]

    def valid(self, price: Decimal) -> bool:
        if not ZERO < price < ONE:
            return False
        for band in self.bands:
            if band.start <= price <= band.end and (price - band.start) % band.step == 0:
                return True
        return False

    def next_above(self, price: Decimal) -> Decimal | None:
        """The smallest valid price strictly above ``price`` (one tick up), or None at the top."""
        best: Decimal | None = None
        for band in self.bands:
            if price >= band.end:
                continue
            if price < band.start:
                candidate = band.start
            else:
                steps = (price - band.start) // band.step + 1
                candidate = band.start + steps * band.step
            if candidate > band.end:
                continue
            if self.valid(candidate) and (best is None or candidate < best):
                best = candidate
        return best


def parse_grid(ranges: Any) -> TickGrid | None:
    """``price_ranges`` must be contiguous bands, each a whole number of positive steps, covering 0 to 1."""
    if not isinstance(ranges, list) or not ranges:
        return None
    bands: list[Band] = []
    for row in ranges:
        if not isinstance(row, Mapping):
            return None
        start, end, step = dec(row.get("start")), dec(row.get("end")), dec(row.get("step"))
        if start is None or end is None or step is None or step <= 0 or end <= start or (end - start) % step:
            return None
        bands.append(Band(start, end, step))
    bands.sort(key=lambda band: band.start)
    if bands[0].start != ZERO or bands[-1].end != ONE:
        return None
    if any(left.end != right.start for left, right in pairwise(bands)):
        return None
    return TickGrid(tuple(bands))


# --------------------------------------------------------------------------- admission (section 4.1)
@dataclass(frozen=True)
class Admission:
    ticker: str
    admitted: bool
    rule: str | None
    reason: str | None
    category: str | None

    def row(self) -> dict[str, Any]:
        return {"ticker": self.ticker, "admitted": self.admitted, "rule": self.rule, "reason": self.reason,
                "category": self.category}


@dataclass(frozen=True)
class FeeStatus:
    """When the series fee-change list and this event's fee-change lookup were last received (UTC seconds)."""

    series_list_at: float | None
    event_lookup_at: float | None


def _sources_ok(*rows: Mapping[str, Any] | None) -> bool:
    for row in rows:
        sources = row.get("settlement_sources") if isinstance(row, Mapping) else None
        for source in sources if isinstance(sources, list) else []:
            url = source.get("url") if isinstance(source, Mapping) else None
            if isinstance(url, str) and url.startswith(("https://", "http://")):
                return True
    return False


def _linked(market: Mapping[str, Any], series: Mapping[str, Any]) -> bool:
    ticker = str(market.get("ticker") or "")
    if ticker.startswith("KXMVE") or str(market.get("event_ticker") or "").startswith("KXMVE"):
        return True
    if series.get("fee_type") == "quadratic_with_combo_maker_fees":
        return True
    return any(key.startswith("mve_") and value not in (None, "", [], {}) for key, value in market.items())


def admit(market: Mapping[str, Any], event: Mapping[str, Any] | None, series: Mapping[str, Any] | None,
          now: float, *, window: tuple[float, float] = PROTOCOL_WINDOW, fees: FeeStatus | None = None,
          check_fees: bool = True) -> Admission:
    """Rules U1-U11 in order; the first failure is the exclusion reason. ``check_fees=False`` skips U10."""
    ticker = str(market.get("ticker") or "")
    category = event.get("category") if isinstance(event, Mapping) else None

    def out(rule: str | None, reason: str | None) -> Admission:
        return Admission(ticker, rule is None, rule, reason, category if isinstance(category, str) else None)

    # U1: the event's category, and the series' category must agree.
    if not isinstance(event, Mapping) or category not in OPEN_CATEGORIES:
        if category in BLOCKED_CATEGORIES:
            return out("U1", "category_blocked")
        return out("U1", "category_unconfirmed")
    if not isinstance(series, Mapping) or series.get("category") != category:
        return out("U1", "category_mismatch")
    if market.get("market_type") != "binary":
        return out("U2", "non_binary")
    if market.get("status") != "active":
        return out("U3", "not_active")
    opened, closes = ts(market.get("open_time")), ts(market.get("close_time"))
    if opened is None or closes is None or closes - opened < MIN_DURATION_S:
        return out("U4", "duration_lt_24h")
    if not window[0] <= closes - now <= window[1]:
        return out("U5", "outside_6h_7d" if window == PROTOCOL_WINDOW else "outside_recording_window")
    if dec(market.get("notional_value_dollars")) != ONE:
        return out("U6", "notional_not_1")
    if not str(market.get("rules_primary") or "").strip() or not _sources_ok(event, series):
        return out("U7", "ambiguous_settlement")
    if market.get("settlement_bounds_type") != "default" or event.get("collateral_return_type") not in ("", None):
        return out("U8", "nonstandard_settlement")
    if _linked(market, series):
        return out("U9", "linked_without_mapping")
    if check_fees:
        multiplier = series.get("fee_multiplier")
        fresh = (fees is not None and fees.series_list_at is not None and fees.event_lookup_at is not None
                 and now - fees.series_list_at <= FEE_FRESH_S and now - fees.event_lookup_at <= FEE_FRESH_S)
        if (series.get("fee_type") not in ("quadratic", "quadratic_with_maker_fees")
                or isinstance(multiplier, bool) or not isinstance(multiplier, (int, float, str))
                or dec(str(multiplier)) is None or not fresh):
            return out("U10", "fee_incomplete")
    if parse_grid(market.get("price_ranges")) is None:
        return out("U11", "tick_unknown")
    return out(None, None)


# --------------------------------------------------------------------------- risk clusters (section 4.3)
_CRYPTO = (("KXBTC", "BTC"), ("KXETH", "ETH"), ("KXSOL", "SOL"), ("KXXRP", "XRP"), ("KXDOGE", "DOGE"),
           ("KXBNB", "BNB"), ("KXHYPE", "HYPE"))
_COMMODITIES = (("KXWTI", "OIL"), ("KXBRENT", "OIL"), ("KXNATGAS", "NATGAS"), ("KXGOLD", "GOLD"),
                ("KXSILVER", "SILVER"), ("KXCOPPER", "COPPER"))
_FINANCIALS = (("KXINX", "US_EQUITY"), ("KXNASDAQ100", "US_EQUITY"), ("KXUST", "US_RATES"),
               ("KX10YRDIR", "US_RATES"), ("KXDDR5", "DDR5"))


def cluster_family(series_ticker: str, tags: Any = None) -> str:
    """The first matching rule of PROTOCOL.md section 4.3; anything else is its own series ticker."""
    for prefix, family in _CRYPTO + _COMMODITIES + _FINANCIALS[:4]:
        if series_ticker.startswith(prefix):
            return family
    if isinstance(tags, list) and "Foreign Exchange" in tags:
        return "FX"
    if series_ticker.startswith(_FINANCIALS[4][0]):
        return _FINANCIALS[4][1]
    for prefix in ("KXHIGHT", "KXHIGH", "KXLOWT", "KXLOW"):
        if series_ticker.startswith(prefix) and len(series_ticker) > len(prefix):
            city = series_ticker[len(prefix):]
            return "TEMP_" + ("NYC" if city in ("NY", "NYC") else city)
    if series_ticker.startswith("KXRAIN"):
        return "RAIN"
    return series_ticker


def cluster_date(event_ticker: str, series_ticker: str, close_time: float | None) -> str | None:
    """The YYMMMDD token right after the series prefix, else the New York date of the close."""
    match = re.match(re.escape(series_ticker) + r"-(\d{2})([A-Z]{3})(\d{2})", event_ticker)
    if match and match.group(2) in _MONTHS:
        year, month, day = int(match.group(1)), _MONTHS.index(match.group(2)) + 1, int(match.group(3))
        try:
            datetime(2000 + year, month, day, tzinfo=UTC)
            return "".join(match.groups())
        except ValueError:
            pass
    if close_time is None:
        return None
    local = datetime.fromtimestamp(close_time, UTC).astimezone(NEW_YORK)
    return f"{local:%y}{_MONTHS[local.month - 1]}{local:%d}"


def cluster_of(series_ticker: str, event_ticker: str, close_time: float | None, tags: Any = None) -> str:
    return f"{cluster_family(series_ticker, tags)}|{cluster_date(event_ticker, series_ticker, close_time)}"


def settlement_block(settlement_ts: float) -> str:
    """Section 4.4: the America/New_York calendar date of a settlement."""
    return datetime.fromtimestamp(settlement_ts, UTC).astimezone(NEW_YORK).date().isoformat()
