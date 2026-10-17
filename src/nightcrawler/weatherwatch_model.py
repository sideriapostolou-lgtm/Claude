"""Pure, read-only weather stopwatch and explicitly conditional quote scenarios.

A station observation is not a final venue settlement. In particular TWC markets
remain observation proxies even after two METAR readings agree. This module has
no credentials, sockets, account resources, or order capability.
"""

from __future__ import annotations

import copy
import math
from datetime import UTC, datetime
from decimal import ROUND_CEILING, ROUND_HALF_EVEN, Decimal
from typing import Any

CAPTURE_SECONDS = 600.0
QUOTE_DELAY_SECONDS = 0.25
BOOK_MAX_AGE_SECONDS = 3.0
RETENTION_SECONDS = 14 * 86400.0
MAX_LATENCY_SAMPLES = 20_000
THRESHOLDS = ("0.97", "0.98")


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def _day(at: float) -> str:
    return datetime.fromtimestamp(at, UTC).strftime("%Y-%m-%d")


def _percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = (len(ordered) - 1) * quantile
    low, high = math.floor(index), math.ceil(index)
    return ordered[low] + (ordered[high] - ordered[low]) * (index - low)


def weather_fee(venue: str, price: float, *, maker: bool = False) -> float | None:
    """One contract, one fill; account-specific rebates are never invented.

    Direct Kalshi cost+fee rounds up to $0.0001. US standard non-combo fees
    round half-even to cents per fill. The observer never simulates maker fills.
    """
    if not math.isfinite(price) or not 0 < price < 1:
        return None
    p = Decimal(str(price))
    if venue == "kalshi":
        return 0.0 if maker else float((p + Decimal("0.07") * p * (1 - p)).quantize(
            Decimal("0.0001"), rounding=ROUND_CEILING) - p)
    if venue == "polymarket_us" and not maker:
        return float((Decimal("0.0695") * p * (1 - p)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_EVEN))
    return None


def observation_kills(market: dict[str, Any], reading: dict[str, Any]) -> bool:
    """Conservative lower/upper measurement bounds against the contract bracket.

    This is a descriptive observation proxy, never an assertion that a different
    settlement source or a corrected report must agree with the reading.
    """
    kind, strike = market.get("kind"), market.get("strike_type")
    floor, cap = _number(market.get("floor")), _number(market.get("cap"))
    lower = _number(reading.get("lower_f"))
    upper = _number(reading.get("upper_f"))
    if market.get("temperature_precision") in {"integer_f", "integer_f_proxy"}:
        lower = math.floor(lower + .5) if lower is not None else None
        upper = math.ceil(upper - .5) if upper is not None else None
    if kind in {"high", "rain"}:
        if kind == "rain":
            lower = _number(reading.get("day_amount_lower"))
        if lower is None:
            return False
        if strike == "less":
            return cap is not None and (lower > cap if market.get("cap_inclusive") is True else lower >= cap)
        if strike == "between":
            return cap is not None and (lower >= cap if market.get("cap_inclusive") is False else lower > cap)
    if kind == "low" and upper is not None:
        if strike == "greater":
            return floor is not None and (upper < floor if market.get("floor_inclusive") is True else upper <= floor)
        if strike == "between":
            return floor is not None and (upper <= floor if market.get("floor_inclusive") is False else upper < floor)
    return False


def observation_side(market: dict[str, Any], reading: dict[str, Any]) -> str | None:
    if observation_kills(market, reading):
        return "no"
    if market.get("kind") == "rain" and market.get("strike_type") == "greater":
        lower, floor = _number(reading.get("day_amount_lower")), _number(market.get("floor"))
        if lower is not None and floor is not None:
            over = lower >= floor if market.get("floor_inclusive") is True else lower > floor
            if over:
                return "yes"
    return None


class WeatherwatchModel:
    """Bounded, JSON-restorable observation state. Every action is read-only."""

    def __init__(self, started_at: float) -> None:
        self.started_at = started_at
        self.last_event_at = started_at
        self.last_tick_at: float | None = None
        self.last_prune_at: float | None = None
        self.markets: dict[str, dict[str, Any]] = {}
        self.books: dict[str, dict[str, Any]] = {}
        self.locks: dict[str, dict[str, Any]] = {}
        self.first_seen: dict[str, float] = {}
        self.seen_trades: dict[str, float] = {}
        self.source_station_seen: dict[str, float] = {}
        self.revision_seen: dict[str, str] = {}
        self.rain: dict[str, list[dict[str, Any]]] = {}
        self.days: dict[str, dict[str, Any]] = {}
        self.health: dict[str, dict[str, Any]] = {}
        self.restarts = 0

    def _daily(self, now: float) -> dict[str, Any]:
        return self.days.setdefault(_day(now), {"day": _day(now), "sources": {},
            "candidate_locks": 0, "confirmed_observation_proxies": 0,
            "gaps": 0, "recorded_seconds": 0.0, "rejected_readings": 0,
            "settlement_disagreements": [], "cli_disagreements": [],
            "trade_prints": 0, "cli_reports": 0, "cli_comparisons": 0})

    def ingest(self, kind: str, data: dict[str, Any], observed_at: float) -> list[dict[str, Any]]:
        if not math.isfinite(observed_at):
            return []
        if observed_at < self.last_event_at:
            self._gap("clock_regression", self.last_event_at)
            return []
        self.last_event_at = observed_at
        self._prune(observed_at)
        if kind in {"market", "weather_market"}:
            identity = str(data.get("market_id", ""))
            if identity and data.get("venue") in {"kalshi", "polymarket_us"}:
                normalized = copy.deepcopy(data)
                for target, alias in (("kind", "weather_type"), ("date", "climate_day"),
                    ("period_start", "day_start"), ("period_end", "day_end"),
                    ("station_verified", "rule_station_verified"), ("floor", "lower"), ("cap", "upper")):
                    if target not in normalized and alias in normalized:
                        normalized[target] = normalized[alias]
                prior_market = self.markets.get(identity)
                guard_fields = ("station", "period_start", "period_end", "kind", "strike_type", "floor", "cap",
                    "floor_inclusive", "cap_inclusive", "settlement_source", "temperature_precision")
                if (prior_market is not None and identity in self.locks
                        and any(prior_market.get(key) != normalized.get(key) for key in guard_fields)):
                    self._revoke(self.locks[identity], "market_rules_changed")
                self.markets[identity] = normalized
        elif kind in {"observation", "weather_observation"}:
            return self._observation(data, observed_at)
        elif kind in {"book", "weather_book", "book_snapshot"}:
            identity = str(data.get("market_id", ""))
            if identity in self.markets:
                self.books[identity] = copy.deepcopy(data)
                return self._assess(identity, observed_at)
        elif kind in {"trade", "public_trade", "weather_trade"}:
            identity = f"{data.get('venue')}:{data.get('market_id')}:{data.get('trade_id')}"
            if str(data.get("market_id", "")) in self.locks and data.get("trade_id") and identity not in self.seen_trades:
                self.seen_trades[identity] = observed_at
                self._daily(observed_at)["trade_prints"] += 1
        elif kind == "weather_watch_rejected":
            lock = self.locks.get(str(data.get("market_id", "")))
            if lock is not None:
                lock["coverage_partial"] = True
                lock["watch_rejected"] = str(data.get("reason", "unknown"))
                for scenario in lock["scenarios"].values():
                    if "entry_price" not in scenario:
                        scenario["status"] = "unknown_watch_rejected"
                    scenario.pop("pending", None)
                    scenario.pop("pending_exit", None)
        elif kind in {"settlement", "weather_settlement"}:
            self._settlement(data, observed_at)
        elif kind in {"cli", "cli_report", "weather_cli"}:
            self._cli(data, observed_at)
        elif kind in {"gap", "weather_gap"}:
            if data.get("reason") == "restart":
                self.restarts += 1
                self.last_tick_at = None
            self._gap(str(data.get("reason", "unknown")), observed_at,
                station=data.get("station"), stations=data.get("stations"),
                venue=data.get("venue"), source=data.get("source"), market_id=data.get("market_id"))
        elif kind in {"health", "weather_source_status", "weather_venue_status"}:
            source = str(data.get("source", data.get("venue", "unknown")))
            self.health[source] = {**data, "observed_at": observed_at}
            failure = (data.get("status") in {"disconnected", "error", "failed", "stale", "unavailable"}
                or data.get("ws_connected") is False)
            if failure:
                self._gap(source, observed_at, station=data.get("station"), stations=data.get("stations"),
                    venue=data.get("venue"), source=data.get("source"))
        return []

    def _gap(self, reason: str, now: float, *, station: Any = None, stations: Any = None,
             venue: Any = None, source: Any = None, market_id: Any = None) -> None:
        self._daily(now)["gaps"] += 1
        if source in {"runtime", "storage", "journal", "clock", "engine", "weatherwatch"}:
            source = None
        station_scope = ({station} if isinstance(station, str) and station else
            {item for item in stations if isinstance(item, str) and item} if isinstance(stations, list) else None)
        affected = {identity for identity, market in self.markets.items()
            if (not market_id or identity == market_id)
            and (station_scope is None or market.get("station") in station_scope)
            and (not venue or market.get("venue") == venue)
            and (not source or venue or self.locks.get(identity, {}).get("last_source") == source)}
        self.books = {identity: book for identity, book in self.books.items() if identity not in affected}
        for identity, lock in self.locks.items():
            if identity in affected and lock["capture_until"] >= now:
                lock["coverage_partial"] = True
                lock["gap_reason"] = reason
                lock["last_valid_at"] = None
                for scenario in lock["scenarios"].values():
                    scenario.pop("pending", None)
                    scenario.pop("pending_exit", None)

    @staticmethod
    def _revoke(lock: dict[str, Any], reason: str) -> None:
        lock["assessment_blocked_reason"] = reason
        lock["classification"] = "revoked_observation_proxy"
        lock["coverage_partial"] = True
        for scenario in lock["scenarios"].values():
            scenario["signal_revoked"] = True
            scenario.pop("pending", None)
            scenario.pop("pending_exit", None)
            if "entry_price" not in scenario:
                scenario["status"] = "unknown_after_observation_revision"

    def _observation(self, data: dict[str, Any], now: float) -> list[dict[str, Any]]:
        station = str(data.get("station", ""))
        source = str(data.get("source", "unknown"))
        valid, received = _number(data.get("valid_at")), _number(data.get("received_at"))
        if not station or valid is None or received is None or not valid <= received <= now:
            self._daily(now)["rejected_readings"] += 1
            return []
        identity = f"{source}:{station}:{data.get('observation_id', valid)}"
        first = identity not in self.first_seen
        revision_id = str(data.get("revision_id", data.get("observation_id", valid)))
        revision = not first and self.revision_seen.get(identity) != revision_id
        self.revision_seen[identity] = revision_id
        # Some public feeds return a whole lookback file on first connection.
        # Every row from that historical batch is left-censored, including rows
        # dated after this process began while broad station discovery ran.
        # Their receipt is observable, their original publication is not.
        bootstrap = (f"{source}:{station}" not in self.source_station_seen or valid < self.started_at
            or data.get("left_censored") is True or data.get("initial_snapshot") is True)
        if first:
            self.source_station_seen.setdefault(f"{source}:{station}", received)
            self.first_seen[identity] = received
            source_day = self._daily(received)["sources"].setdefault(source, {
                "readings": 0, "latency_samples_s": [], "overflow": False,
                "bootstrap_readings": 0, "bootstrap_samples_s": [], "bootstrap_overflow": False})
            source_day["readings"] += 1
            samples_key = "bootstrap_samples_s" if bootstrap else "latency_samples_s"
            overflow_key = "bootstrap_overflow" if bootstrap else "overflow"
            if bootstrap:
                source_day["bootstrap_readings"] += 1
            if len(source_day[samples_key]) < MAX_LATENCY_SAMPLES:
                source_day[samples_key].append(received - valid)
            else:
                source_day[overflow_key] = True
        if not first and not revision:
            return []
        actions: list[dict[str, Any]] = []
        for market_id, market in self.markets.items():
            start, end = _number(market.get("period_start")), _number(market.get("period_end"))
            if (market.get("supported") is False or market.get("station") != station
                    or market.get("station_verified") is not True
                    or start is None or end is None or not start <= valid < end):
                continue
            prior = self.locks.get(market_id)
            metric = market.get("kind")
            # A temperature-only feed did not observe precipitation at all.
            # Its unavailable/unknown rain fields must neither confirm nor
            # interrupt a chain of actual rainfall observations (and vice versa).
            if ((metric == "rain" and data.get("precipitation_status") == "not_requested")
                    or (metric in {"high", "low"} and data.get("temperature_status") == "not_requested")):
                continue
            quality_field = "precipitation_quality" if metric == "rain" else "temperature_quality"
            if data.get(quality_field, data.get("quality")) != "accepted":
                if prior is not None:
                    prior["last_valid_at"] = None
                    if revision:
                        self._revoke(prior, "observation_quality_revision")
                self._daily(now)["rejected_readings"] += 1
                continue
            reading = dict(data)
            if market.get("kind") in {"high", "low"}:
                lower, upper = _number(reading.get("lower_f")), _number(reading.get("upper_f"))
                if lower is None or upper is None or lower > upper:
                    if prior is not None:
                        prior["last_valid_at"] = None
                    continue
            if market.get("kind") == "rain":
                amount = self._rain_amount(station, start, valid, reading)
                if amount is None:
                    if prior is not None:
                        prior["last_valid_at"] = None
                        if revision or reading.get("precipitation_conflict"):
                            self._revoke(prior, "precipitation_interval_revision")
                    continue
                reading["day_amount_lower"] = amount
                reading["day_total_known"] = False
            side = observation_side(market, reading)
            killed = side is not None
            if prior is not None and revision and not killed:
                self._revoke(prior, "observation_value_revision")
            if prior is None and killed:
                prior = {"market_id": market_id, "venue": market["venue"], "side": side,
                    "first_candidate_at": received, "first_valid_at": valid,
                    "first_source": source, "capture_until": received + CAPTURE_SECONDS,
                    "confirmed_at": None, "last_valid_at": valid,
                    "last_independent_id": str(data.get("independent_id", f"{station}:{valid}")),
                    "last_source": source, "coverage_partial": bootstrap,
                    "left_censored_initial_reading": bootstrap, "scenarios": {
                        threshold: {"threshold": float(threshold), "quantity": 1,
                                    "status": "awaiting_confirmation"} for threshold in THRESHOLDS},
                    "classification": "observation_proxy", "qualified_lock": False,
                    "qualification_reason": "METAR is not an irrevocable venue settlement",
                    "samples": 0, "last_sample_second": None,
                    "rain_day_total_known": False if market.get("kind") == "rain" else None,
                    "rain_lower_bound_method": "maximum_single_complete_in_day_interval" if market.get("kind") == "rain" else None}
                self.locks[market_id] = prior
                self._daily(received)["candidate_locks"] += 1
                actions.append(self._watch(prior))
                continue
            if prior is None or prior.get("confirmed_at") is not None:
                continue
            if market.get("kind") == "rain":
                # A later dry reading does not independently corroborate an
                # earlier wet sensor value. Each confirming interval itself
                # must cross the threshold; a retained day lower bound alone
                # cannot create the second confirmation.
                current_interval = {**reading, "day_amount_lower": reading.get("amount_lower")}
                if observation_side(market, current_interval) != side:
                    prior["last_valid_at"] = None
                    continue
            last_valid = _number(prior.get("last_valid_at"))
            if last_valid is not None and valid < last_valid:
                continue  # The same METAR from another gateway is not confirmation.
            if not killed or side != prior.get("side", "no"):
                prior["last_valid_at"] = None
                continue
            independent_id = str(data.get("independent_id", f"{station}:{valid}"))
            distinct = (last_valid is not None and valid > last_valid
                        and independent_id != prior.get("last_independent_id"))
            independent_minute = (data.get("independent_1m") is True
                and data.get("resolution_s") == 60 and source != prior.get("last_source")
                and independent_id != prior.get("last_independent_id")
                and valid >= prior["first_valid_at"])
            if distinct or independent_minute:
                prior["confirmed_at"] = now
                prior["confirmation_delay_s"] = now - prior["first_candidate_at"]
                prior["classification"] = "confirmed_observation_proxy"
                # Explicit source and day evidence is necessary, but preliminary
                # station readings still cannot become guaranteed settlement.
                prior["source_qualified"] = (market.get("source_qualified") is True
                    and market.get("period_verified") is True)
                prior["capture_until"] = max(prior["capture_until"], now + CAPTURE_SECONDS)
                for scenario in prior["scenarios"].values():
                    scenario["status"] = "awaiting_fresh_book"
                self._daily(now)["confirmed_observation_proxies"] += 1
                actions.extend([self._watch(prior), {"kind": "confirmed_proxy", **copy.deepcopy(prior)}])
                actions.extend(self._assess(market_id, now))
            prior["last_valid_at"] = valid
            prior["last_independent_id"] = independent_id
            prior["last_source"] = source
        return actions

    def _rain_amount(self, station: str, start: float, valid: float,
                     reading: dict[str, Any]) -> float | None:
        left, right = _number(reading.get("interval_start")), _number(reading.get("interval_end"))
        lower, upper = _number(reading.get("amount_lower")), _number(reading.get("amount_upper"))
        if (reading.get("interval_complete") is not True or reading.get("trace") is True
                or None in (left, right, lower, upper)):
            return None
        assert left is not None and right is not None and lower is not None and upper is not None
        if left < start or right > valid or left >= right or lower < 0 or upper < lower:
            return None
        key = f"{station}:{start}"
        intervals = self.rain.setdefault(key, [])
        existing = next((row for row in intervals if row["start"] == left and row["end"] == right), None)
        if existing is not None and (existing["lower"] != lower or existing["upper"] != upper):
            existing["conflict"] = True
            reading["precipitation_conflict"] = True
            return None
        elif existing is None:
            intervals.append({"start": left, "end": right, "lower": lower, "upper": upper})
        # Every verified interval wholly inside this climate day bounds its
        # total from below, even when earlier hours were not observed. Taking
        # the maximum cannot double-count overlapping or rolling intervals.
        # This never estimates missing precipitation as zero or claims a known
        # full-day accumulation; that requires a final official report.
        values = [row["lower"] for row in intervals if not row.get("conflict") and row["end"] <= valid]
        return max(values) if values else None

    @staticmethod
    def _watch(lock: dict[str, Any]) -> dict[str, Any]:
        return {"kind": "watch_request", "market_id": lock["market_id"],
                "venue": lock["venue"], "until": lock["capture_until"],
                "first_candidate_at": lock["first_candidate_at"],
                "signal_id": f"{lock['market_id']}:{lock['first_candidate_at']}"}

    def _fresh_book(self, identity: str, now: float) -> dict[str, Any] | None:
        book = self.books.get(identity)
        if (not book or book.get("valid") is not True or book.get("complete") is not True
                or book.get("venue") != self.markets[identity].get("venue")):
            return None
        received = _number(book.get("received_at"))
        if received is None or not 0 <= now - received <= BOOK_MAX_AGE_SECONDS:
            return None
        source_time = _number(book.get("exchange_at"))
        requested = _number(book.get("requested_at"))
        anchor = requested if book.get("source") == "rest" else source_time
        if anchor is None or not 0 <= now - anchor <= BOOK_MAX_AGE_SECONDS:
            return None
        return book

    @staticmethod
    def _levels(book: dict[str, Any], side: str) -> list[tuple[float, float]]:
        result: list[tuple[float, float]] = []
        seen: set[float] = set()
        raw = book.get(side)
        if not isinstance(raw, list):
            return result
        for row in raw:
            if not isinstance(row, (list, tuple)) or len(row) != 2:
                return []
            price, quantity = _number(row[0]), _number(row[1])
            if price is None or quantity is None or not 0 < price < 1 or quantity < 0:
                return []
            if price in seen:
                return []  # Conflicting/duplicated levels do not create depth.
            seen.add(price)
            if quantity:
                result.append((price, quantity))
        return sorted(result, reverse=side.endswith("_bids"))

    def _assess(self, identity: str, now: float) -> list[dict[str, Any]]:
        lock = self.locks.get(identity)
        if (not lock or lock.get("confirmed_at") is None or now > lock["capture_until"]
                or lock.get("watch_rejected") or lock.get("assessment_blocked_reason")):
            return []
        book = self._fresh_book(identity, now)
        if book is None:
            return []
        side = lock.get("side", "no")
        if not isinstance(book.get(f"{side}_asks"), list) or not isinstance(book.get(f"{side}_bids"), list):
            return []
        asks, bids = self._levels(book, f"{side}_asks"), self._levels(book, f"{side}_bids")
        if asks and bids and bids[0][0] >= asks[0][0]:
            return []
        actions: list[dict[str, Any]] = []
        for threshold, scenario in lock["scenarios"].items():
            available = [(price, size) for price, size in asks if price <= float(threshold)]
            if "assessed_at" not in scenario:
                scenario.update({"assessed_at": now, "depth_at_threshold": sum(q for _, q in available),
                    "book_received_at": book["received_at"],
                    "decision_delay_s": now - lock["first_candidate_at"]})
            if scenario["status"] == "awaiting_fresh_book":
                if available and available[0][1] >= 1:
                    scenario["pending"] = {"price": available[0][0], "at": now,
                        "received_at": book["received_at"]}
                    scenario["status"] = "checking_quote_persistence"
                else:
                    scenario["status"] = "no_single_level_contract_at_assessment"
            elif scenario["status"] == "checking_quote_persistence":
                pending = scenario.get("pending")
                if pending is None:
                    scenario["status"] = "unknown_after_gap"
                    continue
                if now < pending["at"] + QUOTE_DELAY_SECONDS:
                    continue
                source_at = book.get("requested_at") if book.get("source") == "rest" else book.get("exchange_at")
                if (book["received_at"] <= pending["received_at"]
                        or book["received_at"] < pending["at"] + QUOTE_DELAY_SECONDS
                        or source_at < pending["at"] + QUOTE_DELAY_SECONDS):
                    continue  # Re-sampling an old snapshot is not persistence evidence.
                executable = next(((p, q) for p, q in available if p <= pending["price"] and q >= 1), None)
                if executable is None:
                    scenario["status"] = "quote_disappeared_after_delay"
                    scenario.pop("pending", None)
                    continue
                price = executable[0]
                fee = weather_fee(lock["venue"], price)
                if fee is None or not self._fee_verified(identity):
                    scenario["status"] = "unknown_fee"
                    continue
                scenario.update({"status": "conditional_quote_entry", "entry_at": now,
                    "entry_price": price, "entry_fee_usd": fee, "entry_cost_usd": price + fee,
                    "latency_to_entry_s": now - lock["first_candidate_at"],
                    "modeled_quote_delay_s": QUOTE_DELAY_SECONDS,
                    "entry_method": "one_contract_single_price_level",
                    "execution_proven": False, "maker_fill_proven": False, "side": side})
                scenario.pop("pending", None)
                actions.append({"kind": "quote_scenario", "market_id": identity,
                    "threshold": threshold, **copy.deepcopy(scenario)})
            elif (scenario["status"] == "conditional_quote_entry" and "exit_price" not in scenario
                  and bids and bids[0][0] >= 0.99 and bids[0][1] >= 1):
                pending_exit = scenario.get("pending_exit")
                if pending_exit is None:
                    scenario["pending_exit"] = {"at": now, "received_at": book["received_at"]}
                    continue
                source_at = book.get("requested_at") if book.get("source") == "rest" else book.get("exchange_at")
                if (now < pending_exit["at"] + QUOTE_DELAY_SECONDS
                        or book["received_at"] <= pending_exit["received_at"]
                        or book["received_at"] < pending_exit["at"] + QUOTE_DELAY_SECONDS
                        or source_at < pending_exit["at"] + QUOTE_DELAY_SECONDS):
                    continue
                fee = weather_fee(lock["venue"], bids[0][0])
                if fee is not None and self._fee_verified(identity):
                    scenario.update({"exit_at": now, "exit_price": bids[0][0],
                        "exit_fee_usd": fee, "conditional_exit_pnl_usd": round(
                            bids[0][0] - fee - scenario["entry_cost_usd"], 8),
                        "exit_method": "quote_persistence_taker_bid_not_resting_fill"})
                    scenario.pop("pending_exit", None)
            elif scenario["status"] == "conditional_quote_entry":
                scenario.pop("pending_exit", None)
        return actions

    def _fee_verified(self, identity: str) -> bool:
        market = self.markets[identity]
        if market.get("fee_verified") is not True:
            return False
        if market["venue"] == "kalshi":
            return (market.get("fee_type") == "quadratic" and market.get("fee_multiplier") == 1
                and market.get("fee_model") == "kalshi_direct" and market.get("fee_precision") == .0001)
        return market.get("fee_coefficient") == .0695 and market.get("fee_model") == "polymarket_us"

    def _settlement(self, data: dict[str, Any], now: float) -> None:
        identity = str(data.get("market_id", ""))
        lock = self.locks.get(identity)
        if not lock or data.get("venue") != lock["venue"] or data.get("result") not in {"yes", "no", "void"}:
            return
        if data.get("final") is not True:
            return
        result = str(data["result"])
        if lock.get("settlement_result") and lock["settlement_result"] != result:
            lock["settlement_conflict"] = True
            for scenario in lock["scenarios"].values():
                scenario.pop("conditional_hold_pnl_usd", None)
            return
        if lock.get("settlement_result"):
            return
        lock["settlement_result"], lock["settled_at"] = result, now
        if result in {"yes", "no"} and result != lock.get("side", "no") and lock.get("confirmed_at") is not None:
            self._daily(now)["settlement_disagreements"].append(identity)
        for scenario in lock["scenarios"].values():
            if "entry_cost_usd" in scenario and result in {"yes", "no"}:
                scenario["conditional_hold_pnl_usd"] = round((1 if result == lock.get("side", "no") else 0)
                                                           - scenario["entry_cost_usd"], 8)

    def _cli(self, data: dict[str, Any], now: float) -> None:
        data = dict(data)
        for target, alias in (("date", "climate_day"), ("high_f", "maximum_f"),
            ("low_f", "minimum_f"), ("rain_inches", "precipitation_in"), ("final", "final_report")):
            if target not in data and alias in data:
                data[target] = data[alias]
        if data.get("final") is not True or data.get("quality") != "accepted":
            return
        report_id = str(data.get("report_id", ""))
        report_key = f"cli:{report_id}:{data.get('revision_id', report_id)}"
        if report_id and report_key in self.first_seen:
            return
        if report_id:
            self.first_seen[report_key] = now
        self._daily(now)["cli_reports"] += 1
        for identity, lock in self.locks.items():
            market = self.markets.get(identity, {})
            if (lock.get("confirmed_at") is None or data.get("station") != market.get("station")
                    or data.get("date") != market.get("date")):
                continue
            reading = {"lower_f": data.get("high_f"), "upper_f": data.get("low_f"),
                       "day_amount_lower": data.get("rain_inches")}
            relevant = {"high": "high_f", "low": "low_f", "rain": "rain_inches"}.get(str(market.get("kind")))
            if relevant and _number(data.get(relevant)) is not None:
                if relevant == "rain_inches" and data.get("precipitation_trace") is True:
                    continue
                if not lock.get("cli_compared"):
                    self._daily(now)["cli_comparisons"] += 1
                lock["cli_compared"] = True
            if (relevant and _number(data.get(relevant)) is not None
                    and observation_side(market, reading) != lock.get("side", "no")
                    and not lock.get("cli_disagreement")):
                lock["cli_disagreement"] = True
                self._daily(now)["cli_disagreements"].append(identity)

    def tick(self, now: float) -> list[dict[str, Any]]:
        """One-second capture samples retain the real book's original timestamps."""
        if not math.isfinite(now) or now < self.last_event_at:
            return []
        if self.last_tick_at is not None:
            elapsed = now - self.last_tick_at
            if 0 <= elapsed <= 2:
                # Count only same-day intervals; a rollover loses <=2s instead of
                # manufacturing a fully recorded day.
                if _day(now) == _day(self.last_tick_at):
                    self._daily(now)["recorded_seconds"] += elapsed
            elif elapsed > 2:
                self._gap("capture_timer_gap", now)
        self.last_tick_at = now
        self.last_event_at = now
        self._prune(now)
        actions: list[dict[str, Any]] = []
        for identity, lock in self.locks.items():
            if lock["capture_until"] < now or lock["last_sample_second"] == int(now):
                continue
            lock["last_sample_second"] = int(now)
            lock["samples"] += 1
            book = self._fresh_book(identity, now)
            if book is None:
                lock["coverage_partial"] = True
            actions.append({"kind": "capture_sample", "market_id": identity,
                "venue": lock["venue"], "sampled_at": now,
                "candidate_delay_s": now - lock["first_candidate_at"],
                "confirmation_delay_s": lock.get("confirmation_delay_s"),
                "book_fresh": book is not None, "book": copy.deepcopy(self.books.get(identity)),
                "classification": lock["classification"], "side": lock.get("side", "no"), "real_orders": False})
            actions.extend(self._assess(identity, now))
        return actions

    def summary(self, now: float) -> dict[str, Any]:
        reports = {day: self.daily_report(day) for day in sorted(self.days)}
        return {"mode": "MEASURE ONLY", "real_orders": False, "started_at": self.started_at,
            "recorded_days": (now - self.started_at) / 86400, "minimum_days": 3,
            "markets": len(self.markets), "candidate_locks": len(self.locks),
            "confirmed_observation_proxies": sum(lock["confirmed_at"] is not None for lock in self.locks.values()),
            "qualified_locks": 0, "qualified_cents_per_day": None,
            "verdict": "Unknown: source qualification and executable fills are not established",
            "scenarios_overlap": True, "scenario_quantity": 1,
            "scenario_method": "Alternative one-contract quote-persistence counterfactuals; never add them",
            "modeled_quote_delay_s": QUOTE_DELAY_SECONDS, "actual_order_latency_s": None,
            "maker_fill_rate": None, "cli_coverage": "unknown_until_final_cli_reports_received",
            "today": self.daily_report(_day(now)), "reports": reports,
            "health": copy.deepcopy(self.health), "restarts": self.restarts}

    def daily_report(self, day: str) -> dict[str, Any]:
        raw = self.days.get(day, {"day": day, "sources": {}})
        result = {key: copy.deepcopy(value) for key, value in raw.items() if key != "sources"}
        result.update({"coverage": "partial", "complete": False, "real_orders": False,
            "qualified_cents_per_day": None, "conditional_scenarios": {}})
        result["sources"] = {}
        for source, measurements in raw.get("sources", {}).items():
            samples = measurements["latency_samples_s"]
            overflow = measurements["overflow"]
            result["sources"][source] = {"readings": measurements["readings"], "unit": "seconds",
                "median": None if overflow else _percentile(samples, 0.5),
                "p95": None if overflow else _percentile(samples, 0.95), "overflow": overflow,
                "latency_samples": len(samples),
                "bootstrap_readings": measurements.get("bootstrap_readings", 0),
                "bootstrap_median_s": None if measurements.get("bootstrap_overflow") else
                    _percentile(measurements.get("bootstrap_samples_s", []), .5),
                "meaning": "post-bootstrap source valid time to first receipt; original publication time is unknown"}
        for venue in ("kalshi", "polymarket_us"):
            scenarios: dict[str, Any] = {}
            for threshold in THRESHOLDS:
                locks = [lock for lock in self.locks.values()
                    if lock["venue"] == venue and _day(lock["first_candidate_at"]) == day]
                rows = [lock["scenarios"][threshold] for lock in locks]
                entries = [row for row in rows if "entry_cost_usd" in row]
                exits = [row for row in entries if "conditional_exit_pnl_usd" in row]
                holds = [row for row in entries if "conditional_hold_pnl_usd" in row]
                scenarios[threshold] = {"candidate_markets": len(rows), "conditional_entries": len(entries),
                    "displayed_contracts_at_assessment": sum(row.get("depth_at_threshold", 0) for row in rows),
                    "unassessed_markets": sum("assessed_at" not in row for row in rows),
                    "revoked_proxy_entries": sum(row.get("signal_revoked") is True for row in entries),
                    "conditional_capital_usd": round(sum(row["entry_cost_usd"] for row in entries), 8),
                    "exit_observations": len(exits), "settled_entries": len(holds),
                    "conditional_exit_pnl_usd": round(sum(row["conditional_exit_pnl_usd"] for row in exits), 8) if exits else None,
                    "conditional_hold_pnl_usd": round(sum(row["conditional_hold_pnl_usd"] for row in holds), 8) if holds else None,
                    "pending_hold_entries": len(entries) - len(holds),
                    "pending_exit_entries": len(entries) - len(exits),
                    "qualified_pnl_usd": None, "execution_proven": False,
                    "resting_exit_pnl_usd": None, "scope": "alternative_one_contract_per_market"}
            result["conditional_scenarios"][venue] = scenarios
        return result

    def _prune(self, now: float) -> None:
        if len(self.markets) > 20_000 or (len(self.first_seen) + len(self.seen_trades)) > 1_000_000 or len(self.locks) > 20_000:
            raise ValueError("Weather stopwatch memory bound exceeded; recording must pause")
        if self.last_prune_at is not None and 0 <= now - self.last_prune_at < 60:
            return
        self.last_prune_at = now
        cutoff = now - RETENTION_SECONDS
        self.first_seen = {key: seen for key, seen in self.first_seen.items() if seen >= cutoff}
        self.seen_trades = {key: seen for key, seen in self.seen_trades.items() if seen >= cutoff}
        self.revision_seen = {key: revision for key, revision in self.revision_seen.items() if key in self.first_seen}
        self.locks = {key: lock for key, lock in self.locks.items() if lock["capture_until"] >= cutoff}
        self.markets = {key: market for key, market in self.markets.items()
            if key in self.locks or (_number(market.get("period_end")) or now) >= cutoff}
        self.books = {key: book for key, book in self.books.items() if key in self.markets}
        self.rain = {key: rows for key, rows in self.rain.items() if rows and rows[-1]["end"] >= cutoff}
        for day in sorted(self.days)[:-14]:
            del self.days[day]

    def state(self) -> dict[str, Any]:
        return copy.deepcopy({"version": 1, "started_at": self.started_at,
            "last_event_at": self.last_event_at, "last_tick_at": self.last_tick_at,
            "last_prune_at": self.last_prune_at,
            "markets": self.markets, "books": self.books, "locks": self.locks,
            "first_seen": self.first_seen, "seen_trades": self.seen_trades,
            "source_station_seen": self.source_station_seen, "revision_seen": self.revision_seen,
            "rain": self.rain, "days": self.days,
            "health": self.health, "restarts": self.restarts})

    @classmethod
    def restore(cls, state: dict[str, Any], now: float) -> WeatherwatchModel:
        if state.get("version") != 1 or _number(state.get("started_at")) is None:
            raise ValueError("Unknown weather stopwatch state; do not reset history silently")
        model = cls(float(state["started_at"]))
        for key in ("markets", "locks", "first_seen", "seen_trades", "source_station_seen", "revision_seen", "rain", "days", "health"):
            value = state.get(key)
            if not isinstance(value, dict):
                raise TypeError("Incomplete weather stopwatch state")
            setattr(model, key, copy.deepcopy(value))
        model.last_event_at = max(float(state.get("last_event_at", now)), now)
        model.last_tick_at = None
        model.last_prune_at = _number(state.get("last_prune_at"))
        model.restarts = int(state.get("restarts", 0)) + 1
        model._gap("restart", model.last_event_at)
        model._prune(now)
        return model
