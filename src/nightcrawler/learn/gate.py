"""Statistical constants of the learning loop (docs/LEARNING.md §5.9). CODE constants, never env vars:
changing one takes a PR, a new ``sim_hash`` and a 7-day promotion freeze.

Phase 1 only uses them for registration (alpha, weekly allowance) and the scoreboard; the pure
promotion/demotion ``step()`` that enforces the rest arrives in phase 2.
"""

from __future__ import annotations

PAPER_ALPHA = 0.005
REG_PER_ISO_WEEK = 4
MAX_ACTIVE = 24
LIVE_ALPHA_TOTAL = 0.01  # alpha_j = 0.01 / (j * (j + 1))
S1_MIN_N = 100
S1_MIN_DAYS = 7
S1_ACTIVE_DAYS = 5
S1_ACTIVE_DAY_TRADES = 5
COST_STRESS = 1.5
CLUSTER_MAX_SHARE = 0.30
PAIRED_E = 20.0
S2_MIN_N = 150
S2_MIN_DAYS = 14
S2_MIN_TWIN_GAP_PP = -1.0
FUTILITY_M = 0.02
FUTILITY_E = 20.0
DRIFT_E = 20.0
CUSUM_REF = -0.01
CUSUM_C_PAPER = 14.0
CUSUM_C_LIVE = 10.0
TWIN_DEMOTE_PP = -2.0
TWIN_WINDOW = 20
VARIANT_DD_DEMOTE = 0.35
PROMOTION_SPACING_D = 7
BENCH_D = 14
FAMILY_FREEZE = (3, 30, 30)  # n, window d, freeze d
PLACEBO_MAX_MEAN = -0.01
PLACEBO_WINDOW = 300
FIDELITY_MIN = 0.95
FIDELITY_MIN_EVALS = 50
COMPLETENESS_MIN = 0.95
SIM_CHANGE_FREEZE_D = 7
LEARNER_STALE_H = 48
LIVE_PROBATION_TRADES = 50  # at MIN_POSITION_USD

#: The e-value a paper registration must reach (1 / PAPER_ALPHA = 200).
PAPER_THRESHOLD = 1.0 / PAPER_ALPHA


def live_alpha(j: int) -> float:
    """alpha of the j-th (1-based) real-money attempt in the bot's lifetime: 0.01 / (j (j + 1))."""
    if j < 1:
        raise ValueError("live attempts are numbered from 1")
    return LIVE_ALPHA_TOTAL / (j * (j + 1))
