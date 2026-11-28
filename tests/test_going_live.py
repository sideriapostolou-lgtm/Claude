"""G39: real money only after the Coach's stage-2 gate, never on "20-30 positive trades".

* docs/GOING_LIVE.md §0 states the gate (>= 150 paper trades over >= 14 days, an anytime-valid lower bound
  on the mean net result above 0, then at most a quarter of Kelly), with the numbers of ``learn/gate.py``;
* the simulation behind it: a strategy with NO edge passes the old rule about half the time, the
  stage-2 e-process almost never;
* the dashboard checklist (:mod:`nightcrawler.readiness`) never says Ready before stage 2 passed.
"""

from __future__ import annotations

import math
import random
from pathlib import Path

import pytest

from nightcrawler.learn.evidence import start, step_up, logmeanexp
from nightcrawler.learn.gate import PAPER_THRESHOLD, S2_MIN_DAYS, S2_MIN_N
from nightcrawler.readiness import CHECK_LABELS, readiness

DOC = Path(__file__).resolve().parents[1] / "docs" / "GOING_LIVE.md"
PROVEN = {"champion": "dip-55", "champion_passed_locked_test": True, "paper_matches_backtest": True}


def checklist() -> str:
    text = DOC.read_text(encoding="utf-8")
    return text[text.index("## 0."):text.index("## 1.")]


def test_the_go_live_checklist_states_the_stage_2_gate() -> None:
    text, section = DOC.read_text(encoding="utf-8"), checklist()
    for folklore in ("20-30", "20–30", "20 to 30"):
        assert folklore not in text
    assert f"{S2_MIN_N} paper trades" in section and f"{S2_MIN_DAYS} days" in section
    assert "lower bound" in section and "quarter of Kelly" in section
    assert "LEARNING.md" in section  # where the gate is specified


#: Zero edge, 15 % rugs (+26 % / -25 % / -90 %, the risk research's trade model): costs already paid.
_P_RUG = 0.15
_P_TP = (0.25 * (1 - _P_RUG) + 0.90 * _P_RUG) / 0.51
_ZERO_EDGE = ((0.26, _P_TP), (-0.25, 1 - _P_TP - _P_RUG), (-0.90, _P_RUG))


def test_a_zero_edge_strategy_passes_20_to_30_trades_half_the_time_and_stage_2_almost_never() -> None:
    values, weights = zip(*_ZERO_EDGE, strict=True)
    assert sum(v * w for v, w in _ZERO_EDGE) == pytest.approx(0.0, abs=1e-12)
    rng = random.Random(2026)
    streams, horizon = 600, 300
    old_passes = gate_passes = 0
    log_threshold = math.log(PAPER_THRESHOLD)  # the first real-money attempt: alpha 0.005, E >= 200
    for _ in range(streams):
        xs = rng.choices(values, weights, k=horizon)
        old_passes += sum(xs[:30]) > 0  # "positive after fees over 30 closed trades"
        logw = start()
        for n, x in enumerate(xs, start=1):
            logw = step_up(logw, x)
            if n >= S2_MIN_N and logmeanexp(logw) >= log_threshold:
                gate_passes += 1
                break
    assert 0.35 <= old_passes / streams <= 0.65
    assert gate_passes / streams <= 0.02


def test_the_checklist_waits_for_stage_2(settings) -> None:
    item = readiness(settings, PROVEN, wallet_address=None, wallet_sol=None)["items"][1]
    assert item["id"] == "paper_match" and not item["done"]
    assert f"{S2_MIN_N}" in item["reason"] and f"{S2_MIN_DAYS}" in item["reason"]
    assert "lower bound" in item["reason"]
    assert f"{S2_MIN_N}" in CHECK_LABELS["paper_match"] and f"{S2_MIN_DAYS}" in CHECK_LABELS["paper_match"]
    for state in ("collecting", "practice", "cash", "paper_champion", "LIVE_READY", None):
        card = {**PROVEN, "state": state}
        assert not readiness(settings, card, wallet_address=None, wallet_sol=None)["items"][1]["done"], state
    for state in ("live_ready", "live"):  # the Coach's stage 2 granted (a live_ready receipt)
        done = readiness(settings, {**PROVEN, "state": state}, wallet_address=None, wallet_sol=None)["items"][1]
        assert done["done"] and "stage 2" in done["reason"], state
    unproven = readiness(settings, {"state": "live_ready", "paper_matches_backtest": True},
                         wallet_address=None, wallet_sol=None)["items"][1]
    assert not unproven["done"] and unproven["reason"] == "Needs a proven strategy first"
