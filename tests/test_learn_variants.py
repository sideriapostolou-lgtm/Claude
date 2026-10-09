"""Variant specs: hard bounds, Settings anchors (tighten only), the variant hash, the families, the seeds
and their registration under the weekly allowance (docs/LEARNING.md §5.2, §7, §8)."""

from __future__ import annotations

import dataclasses

import pytest

from nightcrawler.learn import variants as v
from nightcrawler.learn.families import dip_rebound, placebo
from nightcrawler.learn.gate import PAPER_ALPHA, PAPER_THRESHOLD, REG_PER_ISO_WEEK
from nightcrawler.learn.store import LearnStore
from nightcrawler.models import Candle, StrategyParams

ANCHOR = StrategyParams()
T = 1_791_475_200.0  # Thursday 2026-10-08


@pytest.fixture
def store(tmp_path):
    with LearnStore(tmp_path / "learn.db") as st:
        yield st


def test_a_spec_is_the_anchor_plus_overrides_and_hashes_canonically() -> None:
    spec = v.make_spec("dip_rebound", {"dip_pct": 0.6, "stop_loss_pct": 0.2}, ANCHOR)
    assert spec.params == {**ANCHOR.to_dict(), "dip_pct": 0.6, "stop_loss_pct": 0.2}
    assert spec.strategy_params() == dataclasses.replace(ANCHOR, dip_pct=0.6, stop_loss_pct=0.2)
    same = v.make_spec("dip_rebound", {"stop_loss_pct": 0.2, "dip_pct": 0.6}, ANCHOR)
    assert spec.hash == same.hash and len(spec.hash) == 64
    assert v.make_spec("dip_rebound", {"dip_pct": 0.61}, ANCHOR).hash != spec.hash
    assert v.make_spec("placebo", {"dip_pct": 0.6, "stop_loss_pct": 0.2}, ANCHOR).hash != spec.hash
    assert spec.promotable and spec.hash == v.variant_hash(spec.family, spec.params, None)


def test_the_hash_covers_the_family_code(monkeypatch) -> None:
    spec = v.make_spec("dip_rebound", {}, ANCHOR)
    frozen = spec.hash
    monkeypatch.setattr(v, "family_code_sha256", lambda family: "0" * 64)  # strategy.py or the family edited
    assert v.variant_hash(spec.family, spec.params, None) != frozen


@pytest.mark.parametrize("overrides", [
    {"stop_loss_pct": 0.99}, {"stop_loss_pct": 0.01}, {"max_hold_min": 1000}, {"dip_pct": 0.1},
    {"confirm_green": 7}, {"take_profit_pct": 5.0}, {"trail_pct": 0.9}, {"dip_lookback_h": 24},
    {"min_buy_sell_ratio": 10}, {"partial_tp_fraction": 0.0},
])
def test_out_of_bounds_specs_are_refused(overrides) -> None:
    with pytest.raises(v.SpecRejected):
        v.make_spec("dip_rebound", overrides, ANCHOR)


@pytest.mark.parametrize("key", ["position_pct", "max_position_usd", "daily_loss_limit_pct", "paper_slippage_bps",
                                 "kill_switch", "made_up"])
def test_risk_or_unknown_keys_are_refused(key) -> None:
    with pytest.raises(v.SpecRejected, match=key):
        v.make_spec("dip_rebound", {key: 0.5}, ANCHOR)


def test_unknown_family_is_refused() -> None:
    with pytest.raises(v.SpecRejected):
        v.make_spec("moonshot", {}, ANCHOR)


@pytest.mark.parametrize("overrides", [
    {"min_liquidity_usd": ANCHOR.min_liquidity_usd / 2}, {"min_age_min": ANCHOR.min_age_min - 1},
    {"max_age_h": ANCHOR.max_age_h + 1}, {"min_mcap_usd": ANCHOR.min_mcap_usd / 2},
    {"max_mcap_usd": ANCHOR.max_mcap_usd * 2}, {"cooldown_min": ANCHOR.cooldown_min - 1},
])
def test_loosening_a_safety_anchor_makes_a_spec_research_only(overrides) -> None:
    spec = v.make_spec("dip_rebound", overrides, ANCHOR)
    assert not spec.promotable  # it may run in the shadow, it can never become champion


def test_tightening_anchors_keeps_a_spec_promotable() -> None:
    spec = v.make_spec("dip_rebound", {"min_liquidity_usd": ANCHOR.min_liquidity_usd * 2, "max_age_h": 12,
                                       "min_age_min": ANCHOR.min_age_min + 5}, ANCHOR)
    assert spec.promotable


def test_families() -> None:
    assert v.FAMILIES == {"dip_rebound": dip_rebound, "placebo": placebo}
    assert dip_rebound.PROMOTABLE and not dip_rebound.CONTROL and dip_rebound.entry_fn("M", T) is None
    assert not placebo.PROMOTABLE and placebo.CONTROL
    offsets = {placebo.offset_s(f"Mint{i}") for i in range(50)}
    assert len(offsets) > 40 and all(0 <= o < placebo.WINDOW_H * 3600 for o in offsets)
    assert placebo.offset_s("Mint1") == placebo.offset_s("Mint1")  # a hash, not randomness


def test_the_placebo_enters_at_its_hash_chosen_time() -> None:
    created = T
    fn = placebo.entry_fn("MintP", created)
    p = ANCHOR
    when = created + p.min_age_min * 60 + placebo.offset_s("MintP")
    window = [Candle(int(when) - 120, 1, 1, 1, 1, 1), Candle(int(when) - 60, 1, 1, 1, 1, 1)]
    assert fn(window, None, p, when - 1).kind == "none"
    signal = fn(window, None, p, when)
    assert signal.kind == "enter" and signal.reason == "placebo"


def test_seeds_are_the_benchmark_three_lab_points_and_two_placebos() -> None:
    seeds = v.seed_specs(ANCHOR)
    assert [s.family for s in seeds] == ["dip_rebound"] * 4 + ["placebo"] * 2
    assert seeds[0].params == ANCHOR.to_dict()  # the Settings benchmark
    assert seeds[4].params == ANCHOR.to_dict()  # the R host: random entries inside the bot's own window
    assert len({s.hash for s in seeds}) == 6 and all(s.promotable for s in seeds[:4])
    assert not seeds[4].promotable and not seeds[5].promotable
    assert all(s.name for s in seeds)


def test_placebo_wide_loosens_the_age_size_and_liquidity_anchors_to_their_hard_limits() -> None:
    """The W host (docs/EXPERIENCE §4.1, B11): coins the Crawler's rules refuse get an outcome too. Loosening
    makes it research-only by make_spec; a control spends no alpha."""
    wide = v.seed_specs(ANCHOR)[5]
    loosened = {k: wide.params[k] for k in v.ANCHORS if wide.params[k] != getattr(ANCHOR, k)}
    assert loosened == {"min_age_min": 0.0, "max_age_h": 50.0, "min_mcap_usd": 0.0, "max_mcap_usd": 1e12,
                        "min_liquidity_usd": 0.0}
    assert {k: wide.params[k] for k in v.BOUNDS} == {k: getattr(ANCHOR, k) for k in v.BOUNDS}  # same exits
    assert wide.control and not wide.promotable


def test_seed_registration_spends_the_week_one_allowance(store) -> None:
    registered = v.register_seeds(store, ANCHOR, T)
    assert len(registered) == 6
    rows = store.variants()
    assert sorted(r["family"] for r in rows) == ["dip_rebound"] * 4 + ["placebo"] * 2
    for row in rows:
        control = row["family"] == "placebo"
        assert row["alpha"] == (0.0 if control else PAPER_ALPHA) and row["threshold"] == PAPER_THRESHOLD
        assert row["t0"] is None and row["source"] == "seed" and row["promotable"] is not control
    assert [o["event"] for o in store.outbox()] == ["register"] * 6
    assert v.register_seeds(store, ANCHOR, T + 60) == []  # idempotent
    assert v.registrations_this_week(store, T) == REG_PER_ISO_WEEK  # the controls spend none of it


def test_a_seed_the_settings_put_out_of_bounds_is_skipped_and_the_others_register(store) -> None:
    """MAX_HOLD_MIN=480 is a valid setting but outside the learner's hard range [5, 360]: the seeds that
    inherit it (the benchmark, the two placebos) are skipped with a reason; the lab points set their own."""
    anchor = dataclasses.replace(ANCHOR, max_hold_min=480.0)
    seeds = v.seed_specs(anchor)
    assert [s.params["max_hold_min"] for s in seeds] == [60.0, 60.0, 60.0]
    rejected = v.rejected_seeds(anchor)
    assert len(rejected) == 3 and all("max_hold_min=480.0 outside its hard range [5, 360]" in r for r in rejected)
    assert rejected[0].startswith("the Settings benchmark")
    assert v.register_seeds(store, anchor, T) == [s.hash for s in seeds]
    assert v.rejected_seeds(ANCHOR) == []


def test_the_weekly_allowance_queues_a_fifth_registration(store) -> None:
    v.register_seeds(store, ANCHOR, T)
    extra = v.make_spec("dip_rebound", {"dip_pct": 0.7}, ANCHOR)
    assert not v.register(store, extra, source="proposal", now=T + 3600)  # this ISO week is spent
    assert store.variant(extra.hash) is None
    assert v.register(store, extra, source="proposal", now=T + 4 * 86400)  # Monday: a new ISO week
    assert store.variant(extra.hash)["source"] == "proposal"


def test_describe_names_a_variant_in_plain_words() -> None:
    assert v.describe(v.make_spec("dip_rebound", {"dip_pct": 0.45, "stop_loss_pct": 0.2}, ANCHOR)).startswith(
        "dip 45%, stop 20%")
    assert v.describe(v.make_spec("placebo", {}, ANCHOR)) == "random entry (control)"
