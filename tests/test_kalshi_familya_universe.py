"""Family A admission rules U1-U11, the tick grid and risk clusters, pinned to PROTOCOL.md sections 4-5."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from kalshi_recorder_fixtures import NOW, event_row, market_row, sample, series_row

from nightcrawler.kalshi_familya_universe import (
    RECORDER_WINDOW,
    FeeStatus,
    admit,
    cluster_date,
    cluster_family,
    cluster_of,
    parse_grid,
    settlement_block,
)

FRESH = FeeStatus(NOW - 3600, NOW - 3600)


def decide(market: dict | None = None, event: dict | None = None, series: dict | None = None, **kwargs: object):
    return admit(market or market_row(), event_row() if event is None else event,
                 series_row() if series is None else series, NOW, **kwargs)  # type: ignore[arg-type]


def test_an_ordinary_weather_market_is_admitted() -> None:
    result = decide(fees=FRESH)
    assert result.admitted and result.rule is None and result.category == "Climate and Weather"


@pytest.mark.parametrize(("category", "reason"), [("Sports", "category_blocked"), ("Politics", "category_blocked"),
                                                  ("Mentions", "category_blocked"), ("Elections", "category_blocked"),
                                                  ("Science and Technology", "category_blocked"),
                                                  ("Entertainment", "category_blocked"),
                                                  ("Economics", "category_unconfirmed"),
                                                  ("Companies", "category_unconfirmed"), ("World", "category_unconfirmed")])
def test_u1_only_the_four_open_categories(category: str, reason: str) -> None:
    result = decide(event=event_row(category=category), fees=FRESH)
    assert (result.rule, result.reason) == ("U1", reason)


def test_u1_event_and_series_must_agree() -> None:
    result = decide(series=series_row(category="Crypto"), fees=FRESH)
    assert (result.rule, result.reason) == ("U1", "category_mismatch")


@pytest.mark.parametrize(("change", "rule", "reason"), [
    ({"market_type": "scalar"}, "U2", "non_binary"),
    ({"status": "closed"}, "U3", "not_active"),
    ({"open_offset": -10 * 3600, "close_offset": 10 * 3600}, "U4", "duration_lt_24h"),
    ({"close_offset": 5 * 3600}, "U5", "outside_6h_7d"),
    ({"close_offset": 8 * 86400}, "U5", "outside_6h_7d"),
    ({"notional_value_dollars": "100.0000"}, "U6", "notional_not_1"),
    ({"rules_primary": ""}, "U7", "ambiguous_settlement"),
    ({"settlement_bounds_type": "custom"}, "U8", "nonstandard_settlement"),
    ({"mve_collection_ticker": "KXMVESPORTS-1"}, "U9", "linked_without_mapping"),
    ({"price_ranges": [{"start": "0.0000", "end": "0.9000", "step": "0.0100"}]}, "U11", "tick_unknown"),
])
def test_each_rule_names_its_reason_in_protocol_order(change: dict, rule: str, reason: str) -> None:
    result = decide(market_row(**change), fees=FRESH)
    assert (result.rule, result.reason) == (rule, reason)


def test_u7_needs_a_settlement_source_url_on_the_event_or_series() -> None:
    event, series = event_row(settlement_sources=[]), series_row()
    series["settlement_sources"] = [{"name": "Somebody", "url": ""}]
    assert decide(event=event, series=series, fees=FRESH).reason == "ambiguous_settlement"


def test_u8_collateral_return_and_u9_combo_fees() -> None:
    assert decide(event=event_row(collateral_return_type="MECNET"), fees=FRESH).reason == "nonstandard_settlement"
    combo = series_row(fee_type="quadratic_with_combo_maker_fees")
    assert decide(series=combo, fees=FRESH).reason == "linked_without_mapping"


def test_u10_fee_terms_must_be_complete_and_fresh() -> None:
    assert decide().reason == "fee_incomplete"  # no fee lookups yet
    stale = FeeStatus(NOW - 27 * 3600, NOW - 3600)
    assert decide(fees=stale).reason == "fee_incomplete"
    assert decide(series=series_row(fee_type="flat"), fees=FRESH).reason == "fee_incomplete"
    assert decide(series=series_row(fee_type="quadratic_with_maker_fees"), fees=FRESH).admitted
    assert decide(check_fees=False).admitted  # the recorder defers U10 to the replay


def test_the_recorder_window_is_wider_than_the_protocol_window() -> None:
    soon = market_row(close_offset=5.5 * 3600)
    assert decide(soon, fees=FRESH).reason == "outside_6h_7d"
    assert decide(soon, window=RECORDER_WINDOW, check_fees=False).admitted
    assert decide(market_row(close_offset=9 * 86400), window=RECORDER_WINDOW,
                  check_fees=False).reason == "outside_recording_window"


def test_tick_grids_penny_and_tapered_deci_cent() -> None:
    penny = parse_grid([{"start": "0.0000", "end": "1.0000", "step": "0.0100"}])
    assert penny is not None
    assert penny.next_above(Decimal("0.55")) == Decimal("0.56")
    assert penny.next_above(Decimal("0.99")) is None
    assert penny.valid(Decimal("0.55")) and not penny.valid(Decimal("0.555")) and not penny.valid(Decimal(1))
    tapered = parse_grid(sample("KXBTC15M-metadata.json")["data"]["markets"][0]["price_ranges"])
    assert tapered is not None
    assert tapered.next_above(Decimal("0.05")) == Decimal("0.051")
    assert tapered.next_above(Decimal("0.099")) == Decimal("0.100")
    assert tapered.next_above(Decimal("0.10")) == Decimal("0.11")
    assert tapered.next_above(Decimal("0.90")) == Decimal("0.901")
    assert parse_grid([{"start": "0", "end": "0.5", "step": "0.01"}, {"start": "0.6", "end": "1", "step": "0.01"}]) is None
    assert parse_grid([{"start": "0", "end": "1", "step": "0.03"}]) is None
    assert parse_grid([{"start": 0.0, "end": 1.0, "step": 0.01}]) is None  # floats are not exact; refused


@pytest.mark.parametrize(("series", "family"), [
    ("KXBTCD", "BTC"), ("KXBTC", "BTC"), ("KXBTC15M", "BTC"), ("KXETHD", "ETH"), ("KXSOLD", "SOL"),
    ("KXWTI", "OIL"), ("KXBRENT", "OIL"), ("KXGOLDD", "GOLD"), ("KXINX", "US_EQUITY"), ("KXINXU", "US_EQUITY"),
    ("KXNASDAQ100", "US_EQUITY"), ("KX10YRDIR", "US_RATES"), ("KXHIGHNY", "TEMP_NYC"), ("KXHIGHNYC", "TEMP_NYC"),
    ("KXHIGHTSEA", "TEMP_SEA"), ("KXLOWTCHI", "TEMP_CHI"), ("KXLOWNY", "TEMP_NYC"), ("KXRAINNYC", "RAIN"),
    ("KXNEWTHING", "KXNEWTHING"),
])
def test_cluster_families(series: str, family: str) -> None:
    assert cluster_family(series) == family


def test_fx_is_found_by_tag_and_dates_come_from_the_event_ticker() -> None:
    assert cluster_family("KXEURUSD", ["Foreign Exchange"]) == "FX"
    assert cluster_date("KXHIGHNY-26OCT14", "KXHIGHNY", None) == "26OCT14"
    assert cluster_date("KXINX-26OCT16H1600", "KXINX", None) == "26OCT16"
    assert cluster_date("KXBTCD-26OCT1617", "KXBTCD", None) == "26OCT16"
    late = datetime(2026, 10, 17, 2, 0, tzinfo=UTC).timestamp()  # 22:00 on Oct 16 in New York
    assert cluster_date("KXODD-ABC", "KXODD", late) == "26OCT16"
    assert cluster_of("KXBTCD", "KXBTCD-26OCT1617", None) == cluster_of("KXBTC", "KXBTC-26OCT1617", None)
    assert cluster_of("KXWTI", "KXWTI-26OCT16", None) == cluster_of("KXBRENT", "KXBRENT-26OCT16", None)


def test_settlement_blocks_are_new_york_days() -> None:
    assert settlement_block(datetime(2026, 10, 14, 3, 30, tzinfo=UTC).timestamp()) == "2026-10-13"
    assert settlement_block(datetime(2026, 10, 14, 11, 9, tzinfo=UTC).timestamp()) == "2026-10-14"
