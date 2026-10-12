"""Offline TRAIN tape description, with an explicitly closed strategy build gate.

Run as ``python -m research.lab9.touch_backtest --archive ... --spot-root ...
--output ...``. No transport, account client, candidate simulation or held-out
execution is implemented here. Public prints are observations, not our fills.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from decimal import ROUND_CEILING, Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from research.lab9.touch_spot_data import Candle, features_at, load_envelopes

PLAN_SHA256 = "3e39bb96d548b68beb6775dfe22d60710382055bf68adcbc47d1dfcf7c2f5534"
SERIES = ("KXBTCMAXMON", "KXBTCMINMON", "KXETHMAXMON", "KXETHMINMON")
MONTHS = tuple([f"2025-{m:02d}" for m in range(10, 13)] + [f"2026-{m:02d}" for m in range(1, 10)])
ZERO, ONE = Decimal(0), Decimal(1)
Json = dict[str, Any]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def timestamp(value: str) -> float:
    result = datetime.fromisoformat(value)
    if result.tzinfo is None:
        raise ValueError("Source timestamp must have a timezone")
    return result.timestamp()


def decimal(value: Any) -> Decimal:
    if not isinstance(value, str):
        raise TypeError("Prices and quantities must retain source decimal strings")
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("Malformed source decimal") from exc
    if not parsed.is_finite():
        raise ValueError("Non-finite source decimal")
    return parsed


def split(month: str) -> str:
    if "2025-10" <= month <= "2026-03":
        return "TRAIN"
    if "2026-04" <= month <= "2026-06":
        return "VAL"
    if "2026-07" <= month <= "2026-09":
        return "TEST"
    return "OUTSIDE"


def scheduled_end(market: Json) -> tuple[float, str]:
    """Match the explicit rules date to the scheduled ET endpoint, never close_time.

    Minute precision in the rule permits seconds 00..59 of that final minute.
    A disagreeing occurrence endpoint is rejected instead of choosing a result-
    dependent timestamp. A market title/ticker is not the rule-date source.
    """
    match = re.search(r"11:59 PM ET on ([A-Za-z]{3} \d{1,2}, \d{4})", market.get("rules_primary", ""))
    if not match:
        raise ValueError("Missing explicit contractual ET end date")
    day = datetime.strptime(match[1], "%b %d, %Y").replace(hour=23, minute=59, tzinfo=ZoneInfo("America/New_York"))
    expected = timestamp(market["expected_expiration_time"])
    if not day.timestamp() <= expected < day.timestamp() + 60:
        raise ValueError("Expected expiration disagrees with rules date")
    occurrence = market.get("occurrence_datetime")
    if occurrence is not None and timestamp(occurrence) != expected:
        raise ValueError("Scheduled occurrence and expected expiration disagree")
    return expected, day.strftime("%Y-%m")


def rule_cohort(market: Json, direction: str) -> str:
    secondary = market.get("rules_secondary", "").lower()
    if direction == "MIN" and "is above the threshold" in secondary:
        return "primary_below_secondary_above_conflict"
    if "calculating the final average" in secondary:
        return "whole_period_final_trim_not_verified_touch"
    if "cumulative dataset" in secondary:
        return "cumulative_trim_conflicts_with_minute_terms"
    return "unclassified_rules_require_review"


def z_bucket(z: float) -> str:
    if not math.isfinite(z) or z < 0:
        return "unsafe_or_unknown"
    for edge, label in [(1.5, "[0,1.5)"), (2, "[1.5,2)"), (3, "[2,3)"), (4, "[3,4)")]:
        if z < edge:
            return label
    return "[4,infinity)"


def days_bucket(days: float) -> str:
    if not math.isfinite(days) or days < 0:
        return "outside"
    if days < 1:
        return "[0,1)"
    for edge, label in [(7, "[1,7]"), (14, "(7,14]"), (21, "(14,21]"), (31, "(21,31]")]:
        if days <= edge:
            return label
    return "outside"


def no_role(trade: Json) -> str:
    """Canonical exposure bit; buy-YES/sell-NO hits a resting NO direction.

    This does not reveal whether the taker opened YES or closed NO. Conflicts
    remain unknown; the deprecated field is never enough by itself.
    """
    outcome = trade.get("taker_outcome_side")
    book = trade.get("taker_book_side")
    implied = {"bid": "yes", "ask": "no"}.get(book) if isinstance(book, str) else None
    if outcome not in {"yes", "no"} or implied != outcome:
        return "unknown"
    if trade.get("taker_side", outcome) != outcome:
        return "unknown"
    return "NO_maker_direction" if outcome == "yes" else "NO_taker_direction"


def direct_unit_taker_fee(price: Decimal) -> Decimal:
    """Contemporary one-contract, one-fill stress; not verified historical fees.

    Model fee first rounds upward to $0.000001; Direct balance debit then rounds
    upward to $0.0001. No rebate or accumulator is invented for a single fill.
    """
    if not price.is_finite() or not ZERO < price < ONE:
        raise ValueError("Unit sensitivity price must be inside (0,1)")
    trade_fee = (Decimal("0.07") * price * (ONE - price)).quantize(Decimal("0.000001"), rounding=ROUND_CEILING)
    debit = (price + trade_fee).quantize(Decimal("0.0001"), rounding=ROUND_CEILING)
    return debit - price


@dataclass
class Cell:
    prints: int = 0
    contracts: Decimal = ZERO
    cash: Decimal = ZERO
    minimum: Decimal | None = None
    maximum: Decimal | None = None
    markets: set[str] = field(default_factory=set)
    winning_markets: set[str] = field(default_factory=set)
    months: set[str] = field(default_factory=set)
    winning_prints: int = 0
    unit_samples: int = 0
    unit_gross_sum: Decimal = ZERO
    unit_stress_sum: Decimal = ZERO
    unit_fee_sum: Decimal = ZERO

    def add(self, ticker: str, month: str, price: Decimal, count: Decimal, won: bool) -> None:
        self.prints += 1
        self.contracts += count
        self.cash += price * count
        self.minimum = price if self.minimum is None else min(self.minimum, price)
        self.maximum = price if self.maximum is None else max(self.maximum, price)
        self.markets.add(ticker)
        self.months.add(month)
        self.winning_prints += int(won)
        if won:
            self.winning_markets.add(ticker)
        if count >= ONE:
            self.unit_samples += 1
            gross = Decimal(int(won)) - price
            fee = direct_unit_taker_fee(price)
            self.unit_gross_sum += gross
            self.unit_stress_sum += gross - fee
            self.unit_fee_sum += fee

    def report(self) -> Json:
        def per_print(value: Decimal) -> str | None:
            return str(value / self.unit_samples) if self.unit_samples else None
        return {
            "prints": self.prints, "printed_contracts": str(self.contracts),
            "distinct_markets": len(self.markets), "distinct_months": len(self.months),
            "NO_winning_markets": len(self.winning_markets),
            "NO_losing_markets": len(self.markets - self.winning_markets),
            "market_win_rate": len(self.winning_markets) / len(self.markets) if self.markets else None,
            "print_win_rate": self.winning_prints / self.prints if self.prints else None,
            "minimum_print_price": str(self.minimum) if self.minimum is not None else None,
            "maximum_print_price": str(self.maximum) if self.maximum is not None else None,
            "size_weighted_print_price": str(self.cash / self.contracts) if self.contracts else None,
            "unit_sensitivity_prints_ge1_contract": self.unit_samples,
            "mean_unit_gross_payoff_at_print": per_print(self.unit_gross_sum),
            "mean_unit_taker_fee_contemporary_direct": per_print(self.unit_fee_sum),
            "mean_unit_payoff_after_contemporary_taker_stress": per_print(self.unit_stress_sum),
            "execution_qualified_pnl": None,
        }


def verified_prints(archive: Path, ticker: str, entry: Json, cutoff: int) -> list[Json]:
    if not re.fullmatch(r"[A-Z0-9-]+", ticker):
        raise ValueError("Invalid ticker path")
    path = archive / "trades" / f"{ticker}.jsonl"
    if digest(path) != entry["sha256"]:
        raise ValueError("Trade archive checksum mismatch")
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    if len(rows) != entry["trades"]:
        raise ValueError("Trade archive count mismatch")
    seen: set[str] = set()
    prior: tuple[float, str] | None = None
    for row in rows:
        key = row.get("trade_id")
        at = timestamp(row["created_time"])
        if not isinstance(key, str) or not key or key in seen or row.get("ticker") != ticker:
            raise ValueError("Missing, duplicate or wrong-market trade identity")
        if at > cutoff or (prior is not None and (at, key) < prior):
            raise ValueError("Future or unordered trade in fixed archive")
        seen.add(key)
        prior = (at, key)
    return rows


def analyze(archive: Path, candles: dict[str, dict[int, Candle]]) -> Json:
    """Only TRAIN prints/results enter cells. VAL and TEST remain unopened."""
    inventory_bytes = (archive / "inventory.json").read_bytes()
    manifest_bytes = (archive / "manifest.json").read_bytes()
    inventory = json.loads(inventory_bytes)
    manifest = json.loads(manifest_bytes)
    cells: defaultdict[tuple[str, ...], Cell] = defaultdict(Cell)
    monthly: defaultdict[str, Cell] = defaultdict(Cell)
    per_market: dict[str, Json] = {}
    counts: Counter[str] = Counter()
    coverage: dict[tuple[str, str], Json] = {}
    for month in MONTHS:
        for series in SERIES:
            coverage[month, series] = {"month": month, "split": split(month), "series": series,
                                      "markets": 0, "finalized_markets": 0,
                                      "trade_archives_present": 0, "early_close_markets": 0}
    features: dict[tuple[str, float], Json] = {}
    for series in SERIES:
        record = inventory["series"][series]
        markets = {row["ticker"]: row for row in record["historical_markets"] + record["live_markets"]}
        asset = "BTC" if "BTC" in series else "ETH"
        direction = "MAX" if "MAX" in series else "MIN"
        for ticker, market in sorted(markets.items()):
            end, month = scheduled_end(market)
            if month not in MONTHS:
                counts["outside_month_markets"] += 1
                continue
            cov = coverage[month, series]
            cov["markets"] += 1
            finalized = market.get("status") == "finalized"
            cov["finalized_markets"] += int(finalized)
            cov["trade_archives_present"] += int(ticker in manifest["markets"])
            cov["early_close_markets"] += int(timestamp(market["close_time"]) < end)
            if split(month) != "TRAIN":
                counts[f"{split(month)}_markets_not_evaluated"] += 1
                continue
            counts["TRAIN_markets"] += 1
            if not finalized or market.get("result") not in {"yes", "no"}:
                counts["TRAIN_unresolved_or_void_markets"] += 1
                continue
            if ticker not in manifest["markets"]:
                counts["TRAIN_missing_trade_archive_markets"] += 1
                continue
            rows = verified_prints(archive, ticker, manifest["markets"][ticker], inventory["cutoff_unix"])
            counts["TRAIN_verified_trade_archive_markets"] += 1
            counts["TRAIN_zero_print_markets"] += int(not rows)
            counts["TRAIN_all_prints"] += len(rows)
            cohort = rule_cohort(market, direction)
            market_cell = Cell()
            per_market[ticker] = {"ticker": ticker, "month": month, "asset": asset,
                                  "direction": direction, "rules_cohort": cohort,
                                  "kalshi_result": market["result"],
                                  "scheduled_end": market["expected_expiration_time"],
                                  "actual_close": market["close_time"],
                                  "all_source_prints": len(rows), "observations": market_cell}
            counts[f"TRAIN_rules_{cohort}"] += 1
            strike_value = market.get("floor_strike" if direction == "MAX" else "cap_strike")
            if isinstance(strike_value, bool) or not isinstance(strike_value, (int, float)) or not math.isfinite(strike_value) or strike_value <= 0:
                raise ValueError("Missing or invalid safe-side strike")
            if market.get("strike_type") != ("greater" if direction == "MAX" else "less"):
                raise ValueError("Direction and strike type conflict")
            for trade in rows:
                at = timestamp(trade["created_time"])
                price, yes, count = (decimal(trade[key]) for key in ("no_price_dollars", "yes_price_dollars", "count_fp"))
                if not ZERO <= price <= ONE or yes + price != ONE or count <= ZERO:
                    raise ValueError("Invalid complement price or printed quantity")
                if trade.get("is_block_trade") is not False:
                    counts["TRAIN_block_or_unknown_prints_excluded"] += 1
                    continue
                if not timestamp(market["open_time"]) <= at <= min(timestamp(market["close_time"]), end):
                    counts["TRAIN_outside_trading_window_prints"] += 1
                    continue
                if not Decimal("0.96") <= price <= Decimal("0.99"):
                    continue
                counts["TRAIN_price_band_prints"] += 1
                decision = math.floor((at - 5) / 3600) * 3600 + 5
                days = (end - decision) / 86400
                key = asset, decision
                if key not in features:
                    features[key] = features_at(candles.get(asset, {}), decision)
                feature = features[key]
                if not feature["eligible"]:
                    counts[f"TRAIN_missing_feature_{feature['reason']}"] += 1
                    continue
                spot = feature["spot"]
                distance = math.log(strike_value / spot) if direction == "MAX" else math.log(spot / strike_value)
                if distance <= 0 or days <= 0:
                    counts["TRAIN_wrong_safe_side_or_expired_prints"] += 1
                    continue
                z = distance / (feature["sigma_annual"] * math.sqrt(days / 365))
                role = no_role(trade)
                bucket = days_bucket(days)
                if bucket == "outside":
                    counts["TRAIN_outside_days_buckets"] += 1
                    continue
                won = market["result"] == "no"
                cell_key = asset, direction, cohort, z_bucket(z), bucket, role
                cells[cell_key].add(ticker, month, price, count, won)
                monthly[month].add(ticker, month, price, count, won)
                market_cell.add(ticker, month, price, count, won)
                counts["TRAIN_descriptive_prints"] += 1
    cell_rows = [dict(zip(("asset", "direction", "rules_cohort", "z_bucket", "days_bucket", "NO_direction"), key)) | cell.report()
                 for key, cell in sorted(cells.items())]
    month_rows = []
    for month in MONTHS[:6]:
        market_count = sum(coverage[month, series]["markets"] for series in SERIES)
        row = {"month": month, "split": "TRAIN", "census_markets": market_count,
               "coverage_status": "no_markets_returned" if not market_count else "observed",
               "not_strategy_pnl": True}
        row.update(monthly[month].report())
        month_rows.append(row)
    return {
        "verdict": "INSUFFICIENT_DATA", "practice_build_gate_passed": False,
        "strategy_returns_computed": False, "candidate_selected": None,
        "VAL_prints_read": 0, "VAL_outcomes_evaluated": 0,
        "TEST_prints_read": 0, "TEST_outcomes_evaluated": 0,
        "execution_qualified_pnl": None, "conditional_strategy_pnl": None,
        "no_fill_scenario_pnl": "0", "no_fill_scenario_is_proven_execution": False,
        "blockers": ["fewer_than_12_nonempty_observed_months", "incompatible_or_conflicting_contract_rules",
                     "missing_historical_CF_index_and_prior_touch_state", "missing_historical_BBO_and_queue",
                     "unverified_historical_fee_and_rounding_regime", "spot_publication_times_assumed_not_recorded"],
        "archive_collection_complete": manifest.get("complete") is True,
        "counts": dict(sorted(counts.items())), "coverage": list(coverage.values()),
        "cells": cell_rows, "months": month_rows,
        "train_markets": [{key: value for key, value in row.items() if key != "observations"}
                          | row["observations"].report() for row in per_market.values()],
        "source_hashes": {"inventory": hashlib.sha256(inventory_bytes).hexdigest(),
                          "manifest": hashlib.sha256(manifest_bytes).hexdigest()},
    }


def write_csv(path: Path, rows: list[Json]) -> None:
    if not rows:
        path.write_text("")
        return
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--spot-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    plan = Path(__file__).with_name("LUCAS_PLAN.md")
    if digest(plan) != PLAN_SHA256:
        raise ValueError("Frozen plan hash changed; do not silently rerun a revised experiment")
    candles = {asset: load_envelopes((args.spot_root / asset).glob("*.json"), product=f"{asset}-USD")
               for asset in ("BTC", "ETH")}
    result = analyze(args.archive, candles)
    result["plan_sha256"] = PLAN_SHA256
    result["code_sha256"] = digest(Path(__file__))
    result["spot_source_hashes"] = {str(path.relative_to(args.spot_root)): digest(path)
                                     for path in sorted(args.spot_root.glob("*/*.json"))}
    args.output.mkdir(parents=True, exist_ok=True)
    for name in ("cells", "months", "coverage", "train_markets"):
        write_csv(args.output / f"KALSHI_{name}.csv", result[name])
    (args.output / "summary.json").write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
    print(json.dumps({key: value for key, value in result.items() if key not in {"cells", "months", "coverage", "train_markets", "spot_source_hashes"}}, indent=2))


if __name__ == "__main__":
    main()
