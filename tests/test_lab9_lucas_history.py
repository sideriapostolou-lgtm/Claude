"""Public history evidence identities, rule dates and non-lookahead classification."""
from __future__ import annotations

import sys
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "research" / "lab9"))
from lucas_history import HISTORY, WALLET, library
from lucas_history_analysis import (
    cash_delta,
    classify,
    reconcile_trades,
    rules_expiry,
    signed_z,
)


def trade(**kwargs: Any) -> dict[str, Any]:
    return {"type": "TRADE", "timestamp": 1740528352, "side": "BUY", "token_id": "123",
            "condition_id": "public-condition", "size": 100, "price": .97,
            "transaction_hash": "public-transaction", "usdc_size": 97, "event_slug": "what-price-will-bitcoin-hit-in-april", **kwargs}


def market(**kwargs: Any) -> dict[str, Any]:
    return {"question": "Will Bitcoin dip to $70k in April?", "groupItemTitle": "$70k",
            "description": 'Binance between April 1, 2025, 00:00 and April 30, 2025, 23:59 in the ET timezone',
            "endDate": "2025-04-30T12:00:00Z", "closed": True, "umaResolutionStatus": "resolved",
            "outcomes": '["Yes", "No"]', "outcomePrices": '["0", "1"]', **kwargs}


def test_wallet_adapter_is_private_and_endpoint_rejects_other_wallet() -> None:
    second = library("history")
    assert HISTORY is not second and second.WALLET == WALLET
    with pytest.raises(ValueError, match="fixed public wallet"):
        second.PublicReader().get("activity", {"user": "another-wallet"})
    with pytest.raises(ValueError, match="fixed public wallet"):
        second.PublicReader().get("orders", {"user": WALLET})


def test_only_fixed_public_libraries_can_be_loaded() -> None:
    with pytest.raises(ValueError):
        library("../../src/nightcrawler/speeddesk_kalshi_client")


def test_same_fill_twice_is_not_deduplicated() -> None:
    row = trade()
    matched, discrepancies = reconcile_trades([row, deepcopy(row)], [row, deepcopy(row)])
    assert len(matched) == 2 and not discrepancies


def test_cross_endpoint_fee_share_difference_is_kept_explicit() -> None:
    activity, reported = trade(), trade(size=99.5)
    matched, discrepancies = reconcile_trades([activity], [reported])
    assert matched[0]["size"] == 100
    assert matched[0]["all_trades_reported_size"] == 99.5
    assert matched[0]["usdc_size"] == 97
    assert len(discrepancies) == 1


def test_ambiguous_changed_fill_sizes_are_rejected() -> None:
    with pytest.raises(ValueError, match="Ambiguous"):
        reconcile_trades([trade(size=10), trade(size=20)], [trade(size=9), trade(size=19)])


@pytest.mark.parametrize("reported", [[trade(timestamp=1740528353)], [trade(), trade()]])
def test_changed_identity_or_multiplicity_cannot_claim_complete_match(reported: list[dict[str, Any]]) -> None:
    with pytest.raises(ValueError, match="differ"):
        reconcile_trades([trade()], reported)


def test_written_month_end_overrides_wrong_metadata_end() -> None:
    result = classify(trade(), market())
    assert result["expiry"] == datetime(2025, 5, 1, 4, tzinfo=UTC).timestamp()
    assert result["metadata_expiry"] == datetime(2025, 4, 30, 12, tzinfo=UTC).timestamp()
    assert result["direction"] == "min" and result["strike"] == 70000
    assert result["no_settlement"] == 1


@pytest.mark.parametrize("status", ["proposed", "disputed", "", None])
def test_closed_price_is_not_a_final_settlement(status: str | None) -> None:
    assert classify(trade(), market(umaResolutionStatus=status))["no_settlement"] is None


def test_annual_event_is_not_core_monthly() -> None:
    result = classify(trade(event_slug="what-price-will-bitcoin-hit-before-2027"), market())
    assert not result["core"] and not result["monthly"]


def test_modern_calendar_rule_can_use_parent_event_end() -> None:
    value = market(description="Binance during the month specified in the title from 00:00 AM ET on the first day to 11:59 PM ET on the last",
                   endDate=None, _event_end="2025-05-01T04:00:00Z")
    assert rules_expiry(trade()["event_slug"], value) == datetime(2025, 5, 1, 4, tzinfo=UTC).timestamp()


def test_shortened_contract_is_not_silently_extended_to_month_end() -> None:
    value = market(description="Binance between April 6 11AM and April 15 11:59PM ET")
    assert rules_expiry(trade()["event_slug"], value) is None


def test_late_start_but_correct_calendar_end_is_supported() -> None:
    value = market(description="Binance between February 6 11AM and February 28 11:59PM ET", endDate="2026-03-01T05:00:00Z")
    assert rules_expiry("what-price-will-bitcoin-hit-in-february-2026", value) == datetime(2026, 3, 1, 5, tzinfo=UTC).timestamp()


@pytest.mark.parametrize(("spot", "strike", "direction", "days", "vol"), [
    (100, 90, "max", 10, .5), (100, 110, "min", 10, .5), (100, 100, "max", 10, .5),
    (100, 110, "max", 0, .5), (100, 110, "max", -1, .5), (100, 110, "max", 1, 0),
])
def test_wrong_side_expiry_and_invalid_vol_cannot_become_far_z(spot: float, strike: float, direction: str, days: float, vol: float) -> None:
    assert signed_z(spot, strike, direction, days, vol) is None


def test_signed_z_symmetric_log_distances() -> None:
    assert signed_z(100, 200, "max", 10, .5) == signed_z(100, 50, "min", 10, .5)


def test_cashflow_classification_does_not_turn_funding_into_profit() -> None:
    assert cash_delta(trade(type="DEPOSIT", usdc_size=100)) == 100
    assert cash_delta(trade(type="WITHDRAWAL", usdc_size=100)) == -100
    assert cash_delta(trade()) == -97
    assert cash_delta(trade(type="UNKNOWN")) is None
