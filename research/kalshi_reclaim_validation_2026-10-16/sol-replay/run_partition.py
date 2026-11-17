"""Own offline dataset adapter/report runner for the declared six-cell proxy."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import gzip
import hashlib
import json
import random
from collections import Counter, defaultdict
from dataclasses import asdict
from decimal import Decimal as D
from pathlib import Path
from typing import Any

from replay import (
    Market,
    QualityPolicy,
    Quote,
    Settlement,
    Side,
    btc_context,
    coinbase_closed_candle,
    current_rules,
    find_entry,
    find_exit,
    hold_control,
    official_side_candle,
    quote_from_row,
    score_trade,
    unknown_entry_risk,
)
from verify_data import verify_dataset

HERE = Path(__file__).resolve().parent
PERIODS = {
    "dev": ("2026-10-03", "2026-10-04"),
    "val": ("2026-10-04", "2026-10-10"),
    "confirmation": ("2026-10-10", "2026-10-13"),
}
POLICY = QualityPolicy(
    bar_guard_ms=1000,
    sample_edge_tolerance_ms=1000,
    max_sample_gap_ms=1500,
    min_samples_per_minute=60,
    signal_quote_max_age_ms=2000,
    execution_snapshot_timeout_ms=2000,
    execution_max_gap_ms=3000,
    ema_warmup_bars=32,
    require_all_prior_candidate_bars=True,
)


def load(path: Path) -> Any:
    return json.loads(path.read_text(), parse_float=D)


def epoch_ms(text: str) -> int:
    stamp = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=dt.timezone.utc)
    return int(stamp.timestamp() * 1000)


def encode(value: Any) -> str:
    return json.dumps(value, indent=2, default=str, ensure_ascii=False) + "\n"


def bootstrap(days: list[D]) -> dict[str, Any]:
    if not days:
        return {"days": 0, "lower": None, "upper": None}
    rng = random.Random(20261016)
    totals = sorted(sum((rng.choice(days) for _ in days), D(0)) for _ in range(4096))
    return {
        "days": len(days),
        "resamples": 4096,
        "seed": 20261016,
        "lower": str(totals[int(0.025 * 4096)]),
        "upper": str(totals[int(0.975 * 4096)]),
    }


def summarize(
    rows: list[dict[str, Any]], planned_windows: int, calendar_days: list[str]
) -> dict[str, Any]:
    known = [r for r in rows if r.get("known")]
    traded = [r for r in known if r.get("entered")]
    day_names = sorted(set(calendar_days))
    if not {r["open_day_utc"] for r in rows} <= set(day_names):
        raise ValueError("Rows outside declared calendar-day denominator")
    if planned_windows < len(rows):
        raise ValueError("Planned universe smaller than metadata rows")
    daily = {
        day: sum(
            (D(r.get("pnl") or "0") for r in known if r["open_day_utc"] == day), D(0)
        )
        for day in day_names
    }
    net = sum((D(r.get("pnl") or "0") for r in known), D(0))
    lower = sum((D(r.get("lower_pnl") or "0") for r in rows), D(0))
    upper = sum((D(r.get("upper_pnl") or "0") for r in rows), D(0))
    balance = peak = drawdown = D(0)
    for row in sorted(rows, key=lambda x: (x["open_ms"], x["ticker"])):
        balance += D(row.get("pnl") or "0") if row.get("known") else D(0)
        peak = max(peak, balance)
        drawdown = max(drawdown, peak - balance)
    best = max((D(r["pnl"]) for r in traded), default=D(0))
    attempts = sum(bool(r.get("attempted")) for r in rows)
    fills = sum(bool(r.get("entered")) for r in rows)
    return {
        "windows": len(rows),
        "planned_windows": planned_windows,
        "metadata_missing_windows": planned_windows - len(rows),
        "known_filled_windows": fills,
        "known_completed_trades": len(traded),
        "positive_trades": sum(D(r["pnl"]) > 0 for r in traded),
        "negative_trades": sum(D(r["pnl"]) < 0 for r in traded),
        "unknown_entered_outcomes": sum(
            bool(r.get("entered")) and not r.get("known", False) for r in rows
        ),
        "unknown_attempted_entries": sum(
            r.get("status") == "unknown_entry" for r in rows
        ),
        "unobservable_pre_signal_windows": sum(
            r.get("status") == "unobservable_candidate" for r in rows
        ),
        "known_policy_abstentions_not_observed_no_signal": sum(
            r.get("status") == "unobservable_candidate" for r in rows
        ),
        "attempted_entries": attempts,
        "observed_snapshot_fill_rate": str(D(fills) / attempts) if attempts else None,
        "reason_counts": dict(Counter(r["status"] for r in rows)),
        "net_known_pnl": str(net),
        "all_attempt_lower_pnl": str(lower),
        "all_attempt_upper_pnl": str(upper),
        "net_known_pnl_per_planned_window": str(net / planned_windows)
        if planned_windows
        else None,
        "net_known_pnl_per_completed_trade": str(net / len(traded)) if traded else None,
        "known_total_fees": str(sum((D(r.get("fees") or "0") for r in traded), D(0))),
        "entry_fees_on_all_known_entries": str(
            sum((D(r.get("entry_fee") or "0") for r in rows), D(0))
        ),
        "worst_known_trade": min(traded, key=lambda r: D(r["pnl"])) if traded else None,
        "largest_known_win_fraction_of_known_net": str(best / net) if net > 0 else None,
        "known_only_peak_to_trough_drawdown": str(drawdown),
        "daily_known_pnl_window_open_utc": {
            day: str(value) for day, value in daily.items()
        },
        "distinct_filled_open_days": sorted(
            {r["open_day_utc"] for r in rows if r.get("entered")}
        ),
        "day_block_known_pnl_interval": bootstrap(list(daily.values())),
        "locked_pnl": "0",
        "locked_reason": "One directional unit, not a two-sided pair strategy.",
        "maker_GTC_fill_rate": None,
        "actual_order_latency_ms": None,
        "latency_reason": "Execution delay fixed at1s/3s; historical API/REST samples do not measure order latency.",
    }


def read_quotes(
    file: Path, markets: dict[str, Market]
) -> tuple[dict[str, list[Quote]], dict[str, Any]]:
    quotes: dict[str, list[Quote]] = defaultdict(list)
    counts: Counter[str] = Counter()
    last: dict[str, int] = {}
    seen: set[tuple[str, int]] = set()
    if not file.exists():
        return quotes, {"file_missing": True}
    with gzip.open(file, "rt", newline="") as stream:
        for index, row in enumerate(csv.DictReader(stream)):
            if index > 1_000_000:
                raise ValueError("Declared CSV row bound exceeded")
            if not row.get("ticker", "").startswith("KXBTC15M-"):
                continue
            counts["btc_rows"] += 1
            ticker = row["ticker"]
            if ticker not in markets:
                counts["outside_selected_markets"] += 1
                continue
            stamp = int(row["ts_ms"])
            if (ticker, stamp) in seen:
                counts["duplicate_timestamp_rows"] += 1
            seen.add((ticker, stamp))
            if ticker in last and stamp < last[ticker]:
                counts["reversed_timestamp_rows"] += 1
            last[ticker] = stamp
            try:
                quote = quote_from_row(row, price_unit="dollars")
                for ask, bid, ask_qty, bid_qty in (
                    (quote.yes_ask, quote.no_bid, quote.yes_ask_qty, quote.no_bid_qty),
                    (quote.no_ask, quote.yes_bid, quote.no_ask_qty, quote.yes_bid_qty),
                ):
                    if ask is not None and bid is not None and ask + bid != D(1):
                        counts["contradictory_complement_price_rows"] += 1
                        raise ValueError("Contradictory redundant prices")
                    if (
                        ask_qty is not None
                        and bid_qty is not None
                        and ask_qty != bid_qty
                    ):
                        counts["contradictory_complement_size_rows"] += 1
                        raise ValueError("Contradictory redundant sizes")
            except (ValueError, KeyError, ArithmeticError):
                # Keep the invalid frame's causal position; don't delete it and
                # make the next valid quote appear continuously available.
                counts["invalid_price_or_size_rows"] += 1
                quote = Quote(
                    stamp, ticker, None, None, None, None, None, None, None, None
                )
            market = markets[ticker]
            if stamp < market.open_ms:
                counts["rows_before_market_open"] += 1
            if stamp >= market.close_ms:
                counts["rows_at_or_after_market_close"] += 1
            if quote.yes_ask is None:
                counts["missing_yes_ask_rows"] += 1
            quotes[ticker].append(quote)
    all_stamps = [q.ts_ms for values in quotes.values() for q in values]
    gaps = [
        b.ts_ms - a.ts_ms
        for values in quotes.values()
        for a, b in zip(values, values[1:])
    ]
    return quotes, {
        **dict(counts),
        "markets_with_book": len(quotes),
        "first_receipt_ms": min(all_stamps) if all_stamps else None,
        "last_receipt_ms": max(all_stamps) if all_stamps else None,
        "largest_within_market_gap_ms": max(gaps) if gaps else None,
        "within_market_gaps_over_3s": sum(g > 3000 for g in gaps),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--partition", choices=PERIODS, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--cards", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.partition == "confirmation":
        freeze = load(args.data_root.parent / "CONFIRMATION_FREEZE.json")
        if not freeze.get("independent_review_approved") or not freeze.get(
            "tests_passed"
        ):
            raise RuntimeError("Confirmation remains sealed")
        for item in freeze["files"]:
            source = args.data_root.parent / item["path"]
            if hashlib.sha256(source.read_bytes()).hexdigest() != item["sha256"]:
                raise RuntimeError("Confirmation implementation hash changed")
    data = args.data_root / args.partition
    identity = verify_dataset(data, *PERIODS[args.partition])
    start, end = map(epoch_ms, PERIODS[args.partition])
    official = load(data / "markets_all.json")
    markets: dict[str, Market] = {}
    raw_markets: dict[str, dict[str, Any]] = {}
    for row in official:
        market = Market(
            row["ticker"],
            epoch_ms(row["open_time"]),
            epoch_ms(row["close_time"]),
            row["floor_strike"],
        )
        if not start <= market.open_ms < market.close_ms <= end:
            raise ValueError("Partition inclusion violation")
        if market.ticker in markets:
            raise ValueError("Duplicate official market")
        markets[market.ticker] = market
        raw_markets[market.ticker] = row
    btc = [
        coinbase_closed_candle(row, 1000)
        for row in load(data / "coinbase_normalized.json")
    ]
    rules = current_rules(load(args.cards))
    candles_by_ticker: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for file in sorted(data.glob("candles_*.json")):
        if file.name.endswith(".receipt.json"):
            continue
        for row in load(file)["markets"]:
            candles_by_ticker[row["market_ticker"]].extend(row["candlesticks"])
    rows_by_cell: dict[str, list[dict[str, Any]]] = defaultdict(list)
    coverage_by_day: dict[str, Any] = {}
    feature_errors: Counter[str] = Counter()
    mismatches: list[dict[str, Any]] = []
    input_hashes = {
        f.name: hashlib.sha256(f.read_bytes()).hexdigest()
        for f in sorted(data.iterdir())
        if f.is_file()
    }
    for day_ms in range(start, end, 86_400_000):
        day = (
            dt.datetime.fromtimestamp(day_ms / 1000, dt.timezone.utc).date().isoformat()
        )
        day_markets = {
            t: m
            for t, m in markets.items()
            if day_ms <= m.open_ms < day_ms + 86_400_000
        }
        quotes, quality = read_quotes(data / f"book_{day}.csv.gz", day_markets)
        coverage_by_day[day] = quality
        local_labels = {}
        settle_file = data / f"settle_{day}.csv"
        if settle_file.exists():
            with settle_file.open(newline="") as stream:
                local_labels = {
                    r["ticker"]: r["result"]
                    for r in csv.DictReader(stream)
                    if r["ticker"].startswith("KXBTC15M-")
                }
        for ticker, market in sorted(
            day_markets.items(), key=lambda pair: pair[1].open_ms
        ):
            side_candles = []
            for raw_bar in candles_by_ticker.get(ticker, []):
                for side in Side:
                    try:
                        side_candles.append(
                            official_side_candle(raw_bar, market, side, 1000)
                        )
                    except (ValueError, KeyError, ArithmeticError):
                        feature_errors["unusable_official_side_bar"] += 1
            raw_market = raw_markets[ticker]
            official_result = raw_market.get("result")
            label = None
            if official_result in ("yes", "no"):
                # Retrieval proves this historical label is available now;
                # use the public settlement timestamp where supplied.
                available = (
                    epoch_ms(raw_market["settlement_ts"])
                    if raw_market.get("settlement_ts")
                    else end
                )
                label = Settlement(
                    ticker, Side(official_result), max(available, market.close_ms), True
                )
            if ticker in local_labels and local_labels[ticker] != official_result:
                mismatches.append(
                    {
                        "ticker": ticker,
                        "publisher": local_labels[ticker],
                        "official": official_result,
                    }
                )
            context = btc_context(market, btc, market.open_ms + 301000, POLICY)
            for delay in (1000, 3000):
                entries = [
                    find_entry(
                        market,
                        quotes.get(ticker, []),
                        side_candles,
                        btc,
                        rule,
                        POLICY,
                        delay,
                    )
                    for rule in rules
                ]
                attempts = [entry for entry in entries if entry.attempt is not None]
                if len(attempts) > 1:
                    raise AssertionError(
                        "Mutually exclusive BTC filters generated multiple entry attempts"
                    )
                entry = attempts[0] if attempts else None
                for exit_policy in ("current_targets", "both_70", "hold_settlement"):
                    key = f"{delay}ms_{exit_policy}"
                    base: dict[str, Any] = {
                        "ticker": ticker,
                        "open_day_utc": day,
                        "open_ms": market.open_ms,
                        "close_ms": market.close_ms,
                        "attempted": entry is not None,
                        "entered": False,
                        "known": True,
                        "pnl": "0",
                        "lower_pnl": "0",
                        "upper_pnl": "0",
                        "fees": "0",
                        "entry_fee": "0",
                        "delay_ms": delay,
                        "candidate_reasons": dict(
                            Counter(
                                reason
                                for item in entries
                                for dec in item.decisions
                                for reason in dec.reasons
                            )
                        ),
                        "btc_context_available": context.available,
                        "btc_context_reason": context.reason,
                        "first_five_btc_return": str(context.first_five_return)
                        if context.first_five_return is not None
                        else None,
                        "btc_close_minus_ema": str(context.decision_close_minus_ema)
                        if context.decision_close_minus_ema is not None
                        else None,
                    }
                    if entry is None:
                        base["status"] = (
                            "unobservable_candidate"
                            if any(e.unknown for e in entries)
                            else "no_signal"
                        )
                    else:
                        assert entry.attempt is not None
                        base.update(
                            {
                                "lane": entry.lane.name,
                                "entry_attempt": asdict(entry.attempt),
                            }
                        )
                        if entry.position is None:
                            risk = unknown_entry_risk(entry)
                            base["status"] = (
                                "unknown_entry" if risk else "observed_unfilled"
                            )
                            if risk:
                                base.update(
                                    {
                                        "known": False,
                                        "pnl": None,
                                        "lower_pnl": str(risk.lower_pnl),
                                        "upper_pnl": str(risk.upper_pnl),
                                    }
                                )
                        else:
                            position = entry.position
                            if exit_policy == "hold_settlement":
                                exits = hold_control(position)
                            else:
                                target = (
                                    D(".70")
                                    if exit_policy == "both_70"
                                    else entry.lane.target
                                )
                                exits = find_exit(
                                    position,
                                    market,
                                    quotes.get(ticker, []),
                                    target,
                                    POLICY,
                                    delay,
                                )
                            score = score_trade(
                                exits,
                                market,
                                label,
                                max(
                                    end + 86_400_000, label.available_ms if label else 0
                                ),
                            )
                            base.update(
                                {
                                    "entered": True,
                                    "known": score.known,
                                    "pnl": str(score.net_pnl)
                                    if score.net_pnl is not None
                                    else None,
                                    "lower_pnl": str(score.lower_pnl),
                                    "upper_pnl": str(score.upper_pnl),
                                    "fees": str(score.total_fees)
                                    if score.total_fees is not None
                                    else None,
                                    "entry_fee": str(position.entry_fee),
                                    "entry_price": str(position.entry_price),
                                    "entry_ms": position.entry_ms,
                                    "status": score.reason,
                                    "holding_gap_count": exits.holding_gap_count,
                                    "largest_holding_gap_ms": exits.largest_holding_gap_ms,
                                    "exit_attempts": len(exits.attempts),
                                    "exit_fill": asdict(exits.filled)
                                    if exits.filled
                                    else None,
                                }
                            )
                    rows_by_cell[key].append(base)
        print(
            json.dumps(
                {
                    "stage": "replayed",
                    "partition": args.partition,
                    "day_utc": day,
                    "windows": len(day_markets),
                }
            ),
            flush=True,
        )
    result = {
        "partition": args.partition,
        "start_ms": start,
        "end_ms": end,
        "planned_windows": (end - start) // 900000,
        "official_selected_windows": len(markets),
        "coverage_by_day": coverage_by_day,
        "feature_errors": dict(feature_errors),
        "publisher_official_label_mismatches": mismatches,
        "cells": {
            key: summarize(
                rows,
                (end - start) // 900000,
                [
                    dt.datetime.fromtimestamp(value / 1000, dt.timezone.utc)
                    .date()
                    .isoformat()
                    for value in range(start, end, 86_400_000)
                ],
            )
            for key, rows in rows_by_cell.items()
        },
        "model": "One-contract sampled-taker proxy; assumed bar publication and execution delay, not verified venue fills.",
        "source_sha": "d5a55bf10c02ddc2b429eec78b1fd847fa1b6760",
        "input_sha256": input_hashes,
        "verified_input_identity": identity,
        "implementation_sha256": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in [Path(__file__), HERE / "replay.py"]
        },
    }
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / (args.partition + "_results.json")).write_text(encode(result))
    with (args.out / (args.partition + "_windows.jsonl")).open("w") as stream:
        for key, rows in rows_by_cell.items():
            for row in rows:
                stream.write(json.dumps({"cell": key, **row}, default=str) + "\n")
    print(
        encode(
            {
                key: {
                    field: value.get(field)
                    for field in [
                        "known_filled_windows",
                        "known_completed_trades",
                        "net_known_pnl",
                        "all_attempt_lower_pnl",
                        "all_attempt_upper_pnl",
                        "unknown_attempted_entries",
                        "unknown_entered_outcomes",
                    ]
                }
                for key, value in result["cells"].items()
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
