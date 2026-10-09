"""The lab's OWN strategy code (research/lab2/s1.py, m1.py; read-only) runs unchanged on a live FlowSnapshot and,
for S1, gives the same outputs as on the lab's B1 rows of the same coin. Skipped without pandas / numpy or when the
research tree is not importable (the Docker image ships src/ only)."""

from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Any

import pytest

from test_flow_parity import COINS, ch_rows, tracker_for

pd = pytest.importorskip("pandas")
np = pytest.importorskip("numpy")
LAB2 = Path(__file__).resolve().parents[1] / "research" / "lab2"
if not (LAB2 / "s1.py").exists():  # pragma: no cover - research tree absent
    pytest.skip("research/lab2 not present", allow_module_level=True)
sys.path.insert(0, str(LAB2))
s1 = pytest.importorskip("s1")
m1 = pytest.importorskip("m1")

MINT = "FBsA4BegePq3q9iyZMyVRPscbxAasLcKgidd9YYUpump"   # graduated 59 s after creation: S1-eligible


class LabSnap:
    """The lab's view of the coin: B1 rows from CryptoHouse raw trades (>= 0.01 SOL, ts <= tau) and graduates
    fields, through the slice of the common.AsOf interface that s1.s1_features reads."""

    def __init__(self, coin: dict[str, Any], t: float) -> None:
        gr = coin["graduate"]
        self.t, self.tau, self.g, self.mint = t, t - 20, float(gr["g_ts"]), coin["mint"]
        self.row = {k: gr[k] for k in ("grad_delay_s", "c_slot", "c_ts", "creator", "vsol0", "curve_top3_buy_sol",
                                       "curve_buy_sol", "curve_n_buyers", "pool_base0")}
        self.row.update(curve_partial=False, created_exact=True)
        rows = [{"slot": c["slot"], "tx_idx": c["tx_idx"], "pix": c["pix"], "ix": c["ix"], "ts": c["ts"],
                 "venue": c["venue"], "is_buy": bool(c["is_buy"]), "wallet_h": s1.wallet_h(c["user"]),
                 "usol": c["usol"], "tok": c["tok"], "x0": c["x0"], "y0": c["y0"],
                 "fees": c["pfee"] + c["cfee"] + c["lp_fee"], "virt_ksol": c["virt"] // 1000}
                for c in ch_rows(coin) if c["usol"] >= 10_000_000 and c["ts"] <= self.tau]
        self.trades = pd.DataFrame(rows)
        self.trades["wallet_h"] = self.trades["wallet_h"].astype(np.uint64)

    def legal_from(self, name: str) -> float:
        return -math.inf

    def __getitem__(self, name: str) -> Any:
        return self.row[name]

    def alive(self, *args: Any, **kwargs: Any) -> bool:
        return True


def _equal(a: Any, b: Any) -> bool:
    if isinstance(a, float) and isinstance(b, float):
        return (math.isnan(a) and math.isnan(b)) or abs(a - b) <= 1e-6 * max(1.0, abs(a))
    return bool(a == b)


@pytest.mark.parametrize("offset", [100, 120, 140])
def test_s1_features_are_identical_on_lab_rows_and_on_the_live_snapshot(offset: int) -> None:
    coin = COINS[MINT]
    t = coin["created_ms"] // 1000 + offset
    s1.clear_cache()
    lab = s1.s1_features(LabSnap(coin, t))
    s1.clear_cache()
    live = s1.s1_features(tracker_for(coin).as_of(t, sol_usd=200.0))
    assert len(lab) > 20 and lab["n_trades"] > 80            # a full feature set, not an early refusal
    assert set(lab) == set(live)
    assert {k: (lab[k], live[k]) for k in lab if not _equal(lab[k], live[k])} == {}


def test_m1_runs_on_the_live_snapshot() -> None:
    coin = COINS["8Tj1fv3MBYj6fjhjRHr1ZWnxqvfbUCV8MwiYD1c1uMoC"]
    snap = tracker_for(coin).as_of(coin["created_ms"] // 1000 + 140, sol_usd=200.0)
    assert m1.m1_class(snap) == "FACTORY"                   # instant graduate whose top-5 buyers own the pool
    ok, info = m1.entry_decision(snap, m1.make_params(1.0, "rhythm"))
    assert ok is False and info["k"] == snap.k              # 2 bars: the 30-bar MECH window is not there yet
    assert m1.strategy(snap, m1.make_params(1.0, "rhythm"), None) is None
