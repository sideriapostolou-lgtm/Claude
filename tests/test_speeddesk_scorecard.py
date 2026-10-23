"""Window-denominator, incomplete-evidence and informational gate regressions."""

from datetime import UTC, datetime

import pytest

from nightcrawler.speeddesk_scorecard import cap_review_eligibility, window_scorecard

DAY = "2026-10-10"
START = datetime(2026, 10, 10, tzinfo=UTC).timestamp()


def window(slug="w", start=START, end=START + 900, venue="kalshi"):
    return {"slug": slug, "start": start, "end": end, "venue": venue}


def fill(identity="f", slug="w", side="up", size=1, price=.4, fee=.01, at=START + 100, role=True):
    return {"fill_id": identity, "window": slug, "side": side, "size": size, "price": price,
            "fee_usd": fee, "at": at, "is_taker": role}


def result(slug="w", pnl=.1, at=START + 901):
    return {"window": slug, "pnl_usd": pnl, "locked_usd": pnl / 2, "direction_usd": pnl / 2, "at": at}


def score(**changes):
    values = {"windows": [window()], "fills": [], "settlements": [], "coverage": {"w": True},
              "scope": "real", "as_of": START + 86401, "day_coverage_complete": True}
    values.update(changes)
    return window_scorecard(DAY, **values)


def test_quiet_windows_are_in_denominator_and_no_orders_do_not_imply_balance_or_roles():
    card = score(windows=[window(), window("quiet", START + 900, START + 1800)],
                 coverage={"w": True, "quiet": True},
                 fills=[fill(), fill("g", side="down", role=False)], settlements=[result()])
    assert card["complete_windows"] == 2 and card["traded_windows"] == card["zero_fill_windows"] == 1
    assert card["both_sides_share"] == .5 and card["both_sides_traded_share"] == 1
    assert card["fills_per_window"] == 1 and card["fills_per_traded_window"] == 2
    assert card["median_imbalance"] == 0 and card["taker_fill_share"] == .5
    assert card["pnl_per_window_usd"] == .05 and card["worst_window_usd"] == .1
    assert card["day_complete"] is True
    quiet = score()
    assert quiet["pnl_usd"] == 0 and quiet["fills"] == 0
    assert quiet["median_imbalance"] is quiet["taker_fill_share"] is quiet["matched_pair_cost_usd"] is None


def test_pair_cost_weights_actual_matched_quantity_and_allocates_unmatched_fees():
    card = score(fills=[fill("a", size=3, price=.3, fee=.03),
                        fill("b", side="down", size=1, price=.5, fee=.02)], settlements=[result()])
    assert card["matched_pairs"] == 1 and card["matched_pair_cost_usd"] == pytest.approx(.83)
    assert card["matched_pair_fees_usd"] == pytest.approx(.03)
    assert card["unmatched_fees_usd"] == pytest.approx(.02)
    assert card["fees_usd"] == pytest.approx(.05) and card["median_imbalance"] == .5
    # Two partial receipts carry their actual fees; order counts are not fill counts.
    partial = score(fills=[fill("a", size=.25, fee=.004), fill("b", size=.75, fee=.006),
                           fill("c", side="down", size=1, price=.5, fee=.01)], settlements=[result()])
    assert partial["fills"] == 3 and partial["matched_pair_cost_usd"] == pytest.approx(.92)
    assert partial["unmatched_fees_usd"] == pytest.approx(0)


def test_actual_unknown_roles_stay_unknown_and_duplicate_metadata_does_not_duplicate_money():
    raw = fill(role=None)
    card = score(fills=[raw, fill("g", side="down", role=False)], settlements=[result()])
    assert card["taker_fill_share"] is None and card["role_coverage"] == .5
    assert card["known_role_taker_share"] == 0 and card["unknown_role_fills"] == 1
    enriched = score(fills=[raw, fill(), fill()], settlements=[result()])
    assert enriched["fills"] == 1 and enriched["fees_usd"] == .01 and enriched["taker_fill_share"] == 1
    conflict = score(fills=[fill(), fill(role=False), fill()], settlements=[result()])
    assert conflict["fills"] == 1 and conflict["role_coverage"] == 0
    assert conflict["taker_fill_share"] is None and conflict["day_complete"]


def test_unknown_history_cannot_be_zero_and_partial_day_cannot_qualify():
    unknown = score(coverage={})
    assert unknown["complete_windows"] == 0 and unknown["unknown_coverage_windows"] == 1
    assert unknown["pnl_usd"] is unknown["fees_usd"] is unknown["fills_per_window"] is None
    assert not unknown["day_complete"]
    assert not score(as_of=START + 3600)["day_complete"]
    assert not score(day_coverage_complete=False)["day_complete"]
    assert not score(coverage={"w": False})["day_complete"]
    assert not score(windows=[])["day_complete"]


def test_missing_settlement_suppresses_complete_pnl_but_keeps_known_subtotal():
    card = score(windows=[window(), window("x")], coverage={"w": True, "x": True},
                 fills=[fill(), fill("g", slug="x")], settlements=[result()])
    assert card["settled_pnl_usd"] == .1 and card["unsettled_traded_windows"] == 1
    assert card["pnl_usd"] is card["locked_usd"] is card["directional_usd"] is None
    assert card["pnl_per_window_usd"] is card["full_cohort_worst_usd"] is None
    assert card["worst_window_usd"] == .1
    assert not card["day_complete"]


def test_window_end_cohort_survives_midnight_and_delayed_settlement():
    old = window("old", START - 1800, START - 900)
    boundary = window("boundary", START - 900, START)
    next_day = window("tomorrow", START + 85500, START + 86400)
    card = score(windows=[old, boundary, next_day], coverage={"boundary": True},
                 fills=[fill(slug="boundary", at=START - 100)],
                 settlements=[result("boundary", at=START + 90000)], as_of=START + 90001)
    assert card["eligible_windows"] == 1 and card["fills"] == 1 and card["pnl_usd"] == .1
    assert card["cohort"] == "window end UTC day"


@pytest.mark.parametrize("bad", [fill(price=float("nan")), fill(size=-1), fill(fee=None),
                                 fill(side="unknown"), fill(at=START + 1000)])
def test_invalid_fill_evidence_invalidates_window_instead_of_fabricating_results(bad):
    card = score(fills=[bad], settlements=[result()])
    assert card["invalid_fill_windows"] == 1 and not card["day_complete"]
    assert card["pnl_usd"] is None


def test_conflicting_fill_identity_and_nonzero_settlement_without_fills_are_incomplete():
    card = score(fills=[fill(), fill(size=2)], settlements=[result()])
    assert card["invalid_fill_windows"] == 1 and card["fees_usd"] is None
    assert score(settlements=[result()])["invalid_fill_windows"] == 1
    bad = result()
    bad["direction_usd"] = 5
    assert score(fills=[fill()], settlements=[bad])["pnl_usd"] is None
    assert score(settlements=[bad])["pnl_usd"] is None
    conflict = score(windows=[window(), window(end=START + 1800)])
    assert not conflict["day_complete"] and conflict["pnl_usd"] is None


def test_venue_and_ledger_scopes_remain_isolated_without_mutating_inputs():
    raw = fill()
    assert score(scope="practice", fills=[raw], settlements=[result(pnl=.5)])["pnl_usd"] == .5
    assert score(scope="real")["pnl_usd"] == 0
    assert raw == fill()
    with pytest.raises(ValueError, match="venues"):
        score(windows=[window(), window("other", venue="polymarket_us")])
    with pytest.raises(ValueError, match="scope"):
        score(scope="combined")


def test_documented_practice_rebates_are_signed_and_never_applied_to_real_scope():
    rows = [fill(size=3, fee=-.03), fill("d", side="down", fee=-.02)]
    card = score(scope="practice", fills=rows, settlements=[result()])
    assert card["fees_usd"] == pytest.approx(-.05)
    assert card["matched_pair_fees_usd"] == pytest.approx(-.03)
    assert card["unmatched_fees_usd"] == pytest.approx(-.02)
    assert score(fills=rows)["invalid_fill_windows"] == 1


def match_evidence(**changes):
    return {"protocol": "skipwatch-execution-v3", "time_tolerance_s": 5, "price_tolerance_usd": .02,
            "held_out": True, "timing_validated": True, "identity_validated": True,
            "coverage_validated": True, "one_to_one": True, "anti_spam_passed": True,
            "baseline_passed": True, "causal_before_event": True, "all_source_fills_denominator": True,
            "strict_gate_passed": True, "recall_lower_bound": .7, "precision_lower_bound": .75,
            "false_positives": 3, **changes}


def positive_days():
    return [{"day": f"2026-10-{day}", "venue": "kalshi", "scope": "real", "day_complete": True,
             "utc_day_ended": True, "pnl_usd": .1} for day in (10, 11, 12)]


def test_review_gate_never_changes_money_and_ignores_current_unfinished_day():
    days = positive_days()
    days.append({"day": "2026-10-13", "utc_day_ended": False, "day_complete": False})
    gate = cap_review_eligibility(days, match=match_evidence())
    assert gate["eligible_for_owner_review"] is True
    assert gate["cap_change_allowed"] is gate["automatic_promotion"] is False
    assert gate["informational_only"] is True


@pytest.mark.parametrize("change", [{"recall_lower_bound": .699}, {"timing_validated": False},
                                    {"coverage_validated": False}, {"one_to_one": False},
                                    {"anti_spam_passed": False}, {"precision_lower_bound": None},
                                    {"false_positives": None}, {"held_out": False},
                                    {"identity_validated": False}, {"time_tolerance_s": 6},
                                    {"price_tolerance_usd": .03}, {"causal_before_event": False},
                                    {"strict_gate_passed": False}, {"protocol": "public-event-proxy"}])
def test_rule_match_target_without_validated_precision_timing_and_antispam_cannot_qualify(change):
    assert not cap_review_eligibility(positive_days(), match=match_evidence(**change))["eligible_for_owner_review"]


def test_precision_validity_threshold_belongs_to_preregistered_antispam_protocol_not_owner_recall_target():
    evidence = match_evidence(precision_lower_bound=.6)
    assert cap_review_eligibility(positive_days(), match=evidence)["eligible_for_owner_review"]
    evidence["anti_spam_passed"] = False
    assert not cap_review_eligibility(positive_days(), match=evidence)["eligible_for_owner_review"]


@pytest.mark.parametrize("change", [{"pnl_usd": 0}, {"pnl_usd": -.1}, {"day_complete": False},
                                    {"day": "2026-10-14"}, {"scope": "practice"}, {"venue": "other"}])
def test_each_latest_completed_day_must_be_complete_positive_and_consecutive(change):
    days = positive_days()
    days[-1].update(change)
    assert not cap_review_eligibility(days, match=match_evidence())["eligible_for_owner_review"]
