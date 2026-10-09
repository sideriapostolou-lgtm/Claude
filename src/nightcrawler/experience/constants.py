"""Every constant of experience (docs/EXPERIENCE.md §4-§8). CODE constants, never env vars: they are part of the
exam ``config_hash``, and none of them is learnable (§7.4). Changing the loss taxonomy, its thresholds or the feature
catalogue changes :data:`TAXONOMY_VERSION`, which re-opens lesson groups (§6.5) - so it takes a reviewed PR.

Statistical constants the Coach already owns (:data:`~nightcrawler.learn.gate.CLUSTER_MAX_SHARE`, the placebo
window and bar) are imported from ``learn/gate.py``, never copied.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from nightcrawler.learn.gate import CLUSTER_MAX_SHARE, PLACEBO_MAX_MEAN, PLACEBO_WINDOW

__all__ = [
    "MEMBERS", "MEMBER_NAMES", "MEMBER_KIND", "CHANCE_MEMBERS", "BAR_MEMBERS", "SELF_CHECK_MEMBERS", "KIND_LABELS",
    "CHIP_WORDS", "RISK_CHIP_WORDS", "GREEN_LABELS", "RED_LABELS", "MIN_DAYS", "BLOCK_MIN_COINS", "BLOCK_MIN_TRADES",
    "CLUSTER_MAX_SHARE", "ALPHA_TOTAL", "STABILITY_WEEK_SHARE", "ROUGH_RANGE_LEVEL", "BOOTSTRAP_N",
    "SKILLS_MEASURABLE", "N_EFF_MIN_DAYS", "SPEED_FAST_FORWARD_S", "SPEED_FAST_HISTORY_S", "SPEEDS", "AGE_BANDS_MIN",
    "AGE_BAND_NAMES", "MCAP_TIERS_USD", "MCAP_TIER_NAMES", "UNKNOWN", "COCOON_MIN", "STRATEGY_MIN_TRADES",
    "STRATEGY_MIN_COINS", "EE_AGE_WINDOWS_S", "EE_MIN_CONTROLS", "EE_DAY_WINDOW", "RADAR_MIN_EXITS",
    "RADAR_MIN_CRASHES", "EARLY_WARNING_SHARE", "JEV_MIN_DECISIONS", "JEV_MIN_NO", "COVERAGE_BAR",
    "COVERAGE_WINDOWS_MIN", "CRAWLER_GATE_MIN", "BROKER_TOL_PP", "BROKER_MIN_FILLS", "RUIN_TOLERANCE",
    "RISK_MIN_DAYS", "PER_RULE_MIN_BLOCKS", "PLACEBO_HOLDS_MIN", "COACH_COVERAGE_TARGET", "COACH_COVERAGE_TOL",
    "PLACEBO_MAX_MEAN", "PLACEBO_WINDOW", "PLAN_MIN_FORWARD_DAYS", "KNOWN_PATTERNS", "ATTR_ENTRY_DRAWS",
    "ATTR_WINDOW_S", "PARTS", "LOSS_TYPES", "LOSS_THRESHOLDS", "BASE_RATE_TYPES", "WARN_IDS", "FEATURES",
    "FEATURE_IDS", "FEATURE_THRESHOLDS", "NOMINATES", "PROPOSALS", "LESSON_Q", "LESSON_MIN_FLAGGED_LOSERS",
    "LESSON_MIN_OPERATORS", "LESSON_MIN_DAYS", "LESSON_WEEKLY_CAP", "LESSON_FIRST_RUN_DAYS", "LESSON_RUN_UTC",
    "FOLKLORE_MIN_DAYS", "FOLKLORE_FEATURES", "CELL_FAMILIES", "LESSON_SPLITS", "OUTBOX_KEYS", "TAXONOMY_VERSION",
    "taxonomy",
]

# --------------------------------------------------------------------------- members and card kinds (§5.1)

#: (id, display name, card kind) in the page's order of ids (``page.MEMBERS``).
MEMBERS: tuple[tuple[str, str, str], ...] = (
    ("crawler", "Crawler", "bar"),
    ("cocoon", "Cocoon", "chance"),
    ("strategy", "Strategy", "chance"),
    ("radar", "Radar", "chance"),
    ("judge", "Jev", "chance"),
    ("broker", "Broker", "bar"),
    ("risk", "Risk", "bar"),
    ("receipts", "Receipts", "self_check"),
    ("coach", "Coach", "self_check"),
)
MEMBER_NAMES = {m: name for m, name, _ in MEMBERS}
MEMBER_KIND = {m: kind for m, _, kind in MEMBERS}
CHANCE_MEMBERS = tuple(m for m, _, kind in MEMBERS if kind == "chance")
BAR_MEMBERS = tuple(m for m, _, kind in MEMBERS if kind == "bar")
SELF_CHECK_MEMBERS = tuple(m for m, _, kind in MEMBERS if kind == "self_check")
#: "Skills shown (99% check): {k} of 4" - only vs-chance cards can show skill.
SKILLS_MEASURABLE = len(CHANCE_MEMBERS)

KIND_LABELS: dict[str, tuple[str, ...]] = {
    "chance": ("not_measured", "not_enough", "no_skill_yet", "skilled", "worse"),
    "bar": ("not_measured", "not_enough", "meets_bar", "below_bar"),
    "self_check": ("not_built", "checks_pass", "check_failed"),
}
CHIP_WORDS: dict[str, dict[str, str]] = {
    "chance": {"not_measured": "Not measured", "not_enough": "Collecting", "no_skill_yet": "No skill yet",
               "skilled": "Skill shown", "worse": "Worse than chance"},
    "bar": {"not_measured": "Not measured", "not_enough": "Collecting", "meets_bar": "Meets the bar",
            "below_bar": "Below the bar"},
    "self_check": {"not_built": "Not built yet", "checks_pass": "Checks pass", "check_failed": "Check failed"},
}
RISK_CHIP_WORDS = {"meets_bar": "Within tolerance", "below_bar": "Over tolerance"}
#: Green only for these; red for these; grey (never amber) for everything else (§9).
GREEN_LABELS = frozenset({"skilled", "meets_bar"})
RED_LABELS = frozenset({"worse", "below_bar", "check_failed"})

# --------------------------------------------------------------------------- bands (§5.1) and counting (§4.7)

#: The same floor on every card: fewer distinct judged UTC days -> "Collecting".
MIN_DAYS = 7
#: Day blocks: consecutive judged days merged until a block holds this many units.
BLOCK_MIN_COINS = 20
BLOCK_MIN_TRADES = 5
#: Lifetime error budget per member: version v spends alpha_v = ALPHA_TOTAL / (v (v + 1)); version 1 = 0.01.
ALPHA_TOTAL = 0.02
#: Stability veto (G54): same sign in both halves and in >= 75 % of weeks with data.
STABILITY_WEEK_SHARE = 0.75
#: Secondary metrics: a 95 % day-block bootstrap "rough range" (never sets a label).
ROUGH_RANGE_LEVEL = 0.95
BOOTSTRAP_N = 1000
#: "about N independent situations (estimated)" only after this many forward days (G53).
N_EFF_MIN_DAYS = 15

# --------------------------------------------------------------------------- cells (§4.6)

#: fast: first_seen - created <= 10 min forward (a proxy until the tape has graduatedAt);
#: g - created <= 60 s on history.
SPEED_FAST_FORWARD_S = 600.0
SPEED_FAST_HISTORY_S = 60.0
SPEEDS = ("fast", "slow")
#: Age bands in minutes since first_seen (forward) or graduation (history).
AGE_BANDS_MIN = (30.0, 120.0, 360.0)
AGE_BAND_NAMES = ("0-30", "30-120", "120-360", ">360")
MCAP_TIERS_USD = (100_000.0, 500_000.0)
MCAP_TIER_NAMES = ("<100k", "100k-500k", ">=500k")
UNKNOWN = "unknown"

# --------------------------------------------------------------------------- the cards (§5.2)

COCOON_MIN = {"blocked": 30, "passed": 30, "bad": 20, "good": 20}
STRATEGY_MIN_TRADES = 60
STRATEGY_MIN_COINS = 40
#: Matched random entries: entry age within +-5 min, then +-15 min, then the same age band.
EE_AGE_WINDOWS_S = (300.0, 900.0)
EE_MIN_CONTROLS = 5
EE_DAY_WINDOW = 1
RADAR_MIN_EXITS = 30
RADAR_MIN_CRASHES = 20
#: A danger signal counts as an exit signal only if it leads the crash on >= 50 % of crashes (G21).
EARLY_WARNING_SHARE = 0.5
JEV_MIN_DECISIONS = 100
JEV_MIN_NO = 30
COVERAGE_BAR = 0.90
COVERAGE_WINDOWS_MIN = (5.0, 15.0, 60.0)
CRAWLER_GATE_MIN = 30
BROKER_TOL_PP = 0.5
BROKER_MIN_FILLS = 50
RUIN_TOLERANCE = 0.05
RISK_MIN_DAYS = 14
#: A Cocoon rule with this many blocks whose VV range lies at or below 0 is flagged "no measurable value" (G08).
PER_RULE_MIN_BLOCKS = 200
#: Placebo exits need the version's holding times of at least this many earlier trades (G36).
PLACEBO_HOLDS_MIN = 20
COACH_COVERAGE_TARGET = 0.80
COACH_COVERAGE_TOL = 0.05
#: Plan fields stay NULL before this many forward days ("no situation history yet").
PLAN_MIN_FORWARD_DAYS = 7

#: Effects known in advance: a card that mainly reproduces one says so rather than claiming skill.
KNOWN_PATTERNS: dict[str, str] = {
    "KP-1": "Random entries in fast coins 0-30 min after graduation lose most (-15.7%)",
    "KP-2": "The dip-rebound family loses after costs",
    "KP-3": "Factory coins' airdropped supply is dumped at once, about 16 min after creation",
    "KP-4": "Mint, freeze, extensions and LP never fail on genuine graduates",
    "KP-5": "Rug stops fill far below the stop price (-84% to -97% against -18%)",
}

# --------------------------------------------------------------------------- attribution (§6.2)

#: Step b: K entry times on the coin, hash-chosen within +-30 min of t_dec.
ATTR_ENTRY_DRAWS = 20
ATTR_WINDOW_S = 1800.0
PARTS = ("market", "cell_choice", "selection", "timing", "exit", "delay", "costs")

# --------------------------------------------------------------------------- loss types (§6.3)

#: In table order (ties of the primary type go to the earlier one).
LOSS_TYPES = ("pipeline_fault", "rug_missed", "regime", "oversize", "late_entry", "bad_entry", "early_exit",
              "late_exit", "cost_eaten", "missed_winner", "variance")
LOSS_THRESHOLDS: dict[str, float] = {
    "candle_max_lag_s": 300.0,  # pipeline_fault: the newest candle older than this at the decision
    "fill_quote_max_err": 0.005,  # pipeline_fault: fill vs quote error above 0.5 pp
    "regime_decile": 0.10,  # regime: the regime score at t_in in the bottom decile ...
    "regime_hour_gap": -0.05,  # ... and same-hour random trades >= 5 pp below their cells' as-of means
    "oversize_equity_share": 0.05,  # oversize: realized dollar loss above 5 % of equity at entry
    "late_entry_delay": -0.02,  # late_entry: delay part <= -2 pp
    "bad_entry": -0.05,  # bad_entry: selection + timing <= -5 pp
    "early_exit_rebound": 0.20,  # early_exit: price >= 1.20 x the exit price ...
    "early_exit_window_s": 3600.0,  # ... within 60 min after the exit
    "early_exit_cap": 0.20,  # the forgone rebound is capped at 20 pp
    "late_exit_mfe": 0.20,  # late_exit: mfe >= +20 % yet x <= 0
    "cost_eaten_model_x": 2.0,  # cost_eaten: costs above 2 x the cost model
    "missed_winner_x": 0.05,  # missed_winner: a vetoed signal's counterfactual x above +5 pp
}
#: Types that also get a luck base rate from random entries (R host) in the same cells and week.
BASE_RATE_TYPES = ("rug_missed", "regime", "bad_entry", "early_exit", "late_exit", "cost_eaten", "variance")

# --------------------------------------------------------------------------- feature catalogue (§6.5)

WARN_IDS = ("copycat", "impersonation", "no_socials", "paid_promo", "low_holders")
#: Every feature is computable AS OF t_dec; ``forward`` / ``history`` name its source (None: not available there).
FEATURES: dict[str, dict[str, str | None]] = {
    "fast": {"text": "fast graduation", "forward": "first_seen - created <= 10 min", "history": "grad_delay_s <= 60"},
    "young": {"text": "younger than 30 min", "forward": "universe row", "history": "g_ts"},
    "low_mcap": {"text": "market cap under $100k", "forward": "candles x supply", "history": "B2 close"},
    "small_trades": {"text": "small average trade", "forward": "snaps volume_m5 / txns_m5",
                     "history": "buy_sol / n_buys over 5 closed bars"},
    "ratio_paint": {"text": "buy/sell count ratio at least 1.2", "forward": "snaps txns_m5",
                    "history": "B2 n_buys / n_sells"},
    "dust_burst": {"text": "dust trade burst", "forward": None, "history": "B2 n_dust"},
    "airdrop_seen": {"text": "airdrop dump seen", "forward": None, "history": "B2 sells burst"},
    "boost_window": {"text": "under 7 min since graduation", "forward": "first_seen proxy", "history": "g_ts"},
    "heat_high": {"text": "launch heat in the top decile", "forward": "census counts", "history": "g_ts counts"},
    "breadth_low": {"text": "most young coins falling", "forward": "candles of other coins",
                    "history": "B2 cross-section"},
    "sol_drop": {"text": "SOL down 3% in 15 min", "forward": "census SOL/USD", "history": "SolUsd closed minutes"},
    **{f"warn:{w}": {"text": f"Cocoon warning {w}", "forward": "decision-row safety.warnings", "history": None}
       for w in WARN_IDS},
}
FEATURE_IDS = tuple(FEATURES)
FEATURE_THRESHOLDS: dict[str, float] = {
    "young_min": 30.0,
    "low_mcap_usd": 100_000.0,
    "small_trade_usd": 5.0,  # G15 proxy: average DexScreener m5 trade below $5
    "ratio_paint": 1.2,  # the bot's own confirm input (MIN_BUY_SELL_RATIO default), fixed here
    "dust_share": 0.5,
    "dust_trades_per_min": 300.0,
    "boost_window_min": 7.0,
    "heat_quantile": 0.9,
    "breadth_drop": -0.20,
    "sol_drop": -0.03,
    "sol_drop_window_s": 900.0,
}
_DANGER = ("fast", "young", "boost_window", "small_trades", "ratio_paint", "dust_burst", "airdrop_seen",
           "warn:copycat", "warn:impersonation", "warn:low_holders")
_REGIME = ("heat_high", "breadth_low", "sol_drop")
_ENTRY = ("fast", "young", "low_mcap", "small_trades", "ratio_paint", "boost_window", *(f"warn:{w}" for w in WARN_IDS))
_EXIT = ("fast", "young", "low_mcap", "breadth_low", "sol_drop")
_COST = ("low_mcap", "small_trades")
#: Which features each loss type nominates for testing; the type itself never enters the test (A1).
NOMINATES: dict[str, tuple[str, ...]] = {
    "pipeline_fault": (), "rug_missed": _DANGER, "regime": _REGIME, "oversize": (), "late_entry": (),
    "bad_entry": _ENTRY, "early_exit": _EXIT, "late_exit": _EXIT, "cost_eaten": _COST, "missed_winner": (),
    "variance": (),
}
#: What a lesson nominated by each type becomes (§6.5): a hypothesis draft, never a change.
PROPOSALS: dict[str, str] = {
    "rug_missed": "veto test (Track F)", "bad_entry": "veto test (Track F)", "regime": "veto test (Track F)",
    "cost_eaten": "veto test (Track F)", "early_exit": "exit-grid cell with placebo exits",
    "late_exit": "exit-grid cell with placebo exits", "late_entry": "engineering ticket to measure speed",
    "oversize": "written note to the owner", "missed_winner": "loosen-or-remove test with the reverse bar",
    "pipeline_fault": "bug ticket",
}

# --------------------------------------------------------------------------- lessons (§6.5)

LESSON_Q = 0.10
LESSON_MIN_FLAGGED_LOSERS = 10
LESSON_MIN_OPERATORS = 5
LESSON_MIN_DAYS = 3
LESSON_WEEKLY_CAP = 3
LESSON_FIRST_RUN_DAYS = 28
#: Monday 03:47 UTC (weekday, hour, minute), or the first learner run after it.
LESSON_RUN_UTC = (0, 3, 47)
#: "Revenge trade" and "tilt" lessons need this many distinct days on top of the bar (§6.6).
FOLKLORE_MIN_DAYS = 7
FOLKLORE_FEATURES = ("reentry_after_stop", "loss_streak")
#: Every group is (feature, family): all coins, plus the 8 speed x age-band cells.
CELL_FAMILIES = ("all", *(f"{s}|{a}" for s in SPEEDS for a in AGE_BAND_NAMES))
#: The only rows lessons may be mined from: forward/paper rows, and history rows of ``train``.
LESSON_SPLITS = ("train",)

# --------------------------------------------------------------------------- outbox events (§11 frozen contract)

#: Idempotency key of each experience outbox event: the payload fields that identify it. Every fold keeps the
#: FIRST receipted row per (event, key).
OUTBOX_KEYS: dict[str, tuple[str, ...]] = {
    "member_version": ("member", "hash"),
    "skill_claim": ("member", "version"),
    "journal_root": ("day",),
    "cells_root": ("snapshot_ts",),
    "lesson": ("lesson_id",),
    "card_week": ("member", "week"),
    "filter_register": ("filter_id",),
    "filter_verdict": ("filter_id",),
    "experience_stop": ("reason", "trade"),
}

# --------------------------------------------------------------------------- the taxonomy version


def taxonomy() -> dict[str, Any]:
    """What the taxonomy version covers: loss types, their thresholds and nominations, the feature catalogue and
    its thresholds, the cell bands and the lesson bar."""
    return {"loss_types": list(LOSS_TYPES), "thresholds": LOSS_THRESHOLDS, "base_rate_types": list(BASE_RATE_TYPES),
            "nominates": {k: list(v) for k, v in NOMINATES.items()}, "features": FEATURES,
            "feature_thresholds": FEATURE_THRESHOLDS,
            "cells": {"speed_s": [SPEED_FAST_FORWARD_S, SPEED_FAST_HISTORY_S], "age_min": list(AGE_BANDS_MIN),
                      "mcap_usd": list(MCAP_TIERS_USD)},
            "lesson_bar": [LESSON_Q, LESSON_MIN_FLAGGED_LOSERS, LESSON_MIN_OPERATORS, LESSON_MIN_DAYS,
                           LESSON_WEEKLY_CAP]}


TAXONOMY_VERSION = hashlib.sha256(json.dumps(taxonomy(), sort_keys=True, separators=(",", ":"))
                                  .encode("utf-8")).hexdigest()
