"""The lab's OWN strategy code (research/lab2/s1.py, m1.py; read-only) runs unchanged on a live FlowSnapshot and,
for S1, gives the same outputs as on the lab's B1 rows of the same coin. Skipped without pandas / numpy or when the
research tree is not importable (the Docker image ships src/ only)."""

from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Any

import pytest

from nightcrawler.flow import POOLED_ACCOUNTS, VENUE_AMM, VENUE_CURVE, FlowTrade, FlowTracker, wallet_h
from test_flow_parity import COINS, MAYHEM, ch_rows, tracker_for

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


@pytest.mark.parametrize("mint", [m for m in COINS if m != MAYHEM and COINS[m]["graduate"]["grad_delay_s"] < 119])
@pytest.mark.parametrize("offset", [100, 140])
def test_wallet_roles_are_s1s_own(mint: str, offset: int) -> None:
    """snap.roles() / orphan_sellers() / inventory() are s1._build_prefix's TRANSFEREE / BUNDLE / SNIPER /
    COMPLETER / INSIDER definitions (per-sell 2 % orphan rule on B1 rows, integer ledger), wallet for wallet."""
    coin = COINS[mint]
    c = coin["created_ms"] // 1000
    snap = tracker_for(coin).as_of(c + offset, sol_usd=200.0)
    assert snap.graduated and snap.curve_known                 # S1 decides on graduated coins only
    st = {"c_slot": snap.c_slot or 0, "c_ts": c, "vsol0": 30.0, "creator": coin["graduate"]["creator"]}
    P = s1._build_prefix(snap.trades.reset_index(drop=True), st, float(snap.g))

    def hashes(mask: Any) -> set[int]:
        return {int(h) for h in P.uw[mask]}

    roles = snap.roles()
    assert {wallet_h(w) for w in roles["transferees"]} == hashes(P.transferee_w)
    assert {wallet_h(w) for w in snap.orphan_sellers()} == hashes(P.transferee_w)
    assert {wallet_h(w) for w in roles["bundle"]} == hashes(P.bundle_w)
    assert {wallet_h(w) for w in roles["snipers"]} == hashes(P.sniper_w)
    assert {wallet_h(w) for w in roles["insiders"]} == hashes(P.ins_w)
    want_comp = {int(P.uw[P.completer_code])} if P.completer_code is not None else set()
    assert {wallet_h(w) for w in roles["completer"]} == want_comp
    ins = snap.inventory()["insiders"]
    assert ins["wallets"] == int(P.ins_w.sum())
    assert ins["held_tok"] == pytest.approx(P.insider_hold, rel=1e-12, abs=1e-9)
    assert ins["peak_tok"] == pytest.approx(P.insider_peak, rel=1e-12, abs=1e-9)
    assert ins["cost_sol"] == pytest.approx(P.insider_cost_sol, rel=1e-9, abs=1e-12)
    assert ins["pos_tok"] == pytest.approx(P.insider_pos_pos, rel=1e-12, abs=1e-9)


_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def _address(i: int) -> str:
    n = int.from_bytes(bytes((i * 37 + k * 11 + 1) % 256 for k in range(32)), "big")
    out = ""
    while n:
        n, r = divmod(n, 58)
        out = _B58[r] + out
    return out


def test_wallet_roles_match_s1_on_transferees_dust_and_an_agent() -> None:
    """The fixture coins have no TRANSFEREE outside the Mayhem coin: a synthetic coin with orphan sells above and
    below the 2 % rule, a dust orphan sell (not a B1 row), a pooled account and a 12 s BOOST cadence."""
    c, g, c_slot = 1_800_000_000, 1_800_000_090, 1_000
    W = [_address(i) for i in range(40)]
    pooled = next(iter(POOLED_ACCOUNTS))
    trades: list[FlowTrade] = []

    def add(ts: int, wallet: str, buy: bool, tok: int, sol: float, venue: int = VENUE_CURVE) -> None:
        slot = c_slot + (ts - c) * 3 + len(trades) % 3
        sid = f"{slot:012d}{len(trades):010d}"
        trades.append(FlowTrade(slot=slot, pos=len(trades), sid=sid, ts=ts, wallet=wallet, is_buy=buy, venue=venue,
                                amount_sol=sol, tok_raw=tok, price=3e-8 if venue == VENUE_CURVE else 4e-7))

    add(c, W[0], True, 50_000_000_000_000, 1.5)                   # creator, creation slot
    add(c, W[1], True, 20_000_000_000_000, 0.6)                   # bundle
    for i in range(2, 26):                                        # snipers: 60 s window, then first 20
        add(c + 3 * i, W[i], True, 5_000_000_000_000 + i, 0.2 + 0.01 * i)
    add(c + 70, W[26], True, 1_000_000_000_000, 0.03)
    add(c + 71, W[26], False, 1_015_000_000_000, 0.03)            # 1.5 % orphan: not a TRANSFEREE
    add(c + 72, W[27], True, 1_000_000_000_000, 0.03)
    add(c + 73, W[27], False, 1_100_000_000_000, 0.033)           # 9 % orphan: TRANSFEREE
    add(c + 74, W[28], False, 900_000_000_000, 0.02)              # sells what it never bought: TRANSFEREE
    add(c + 75, W[29], False, 900_000_000_000, 0.004)             # the same, but dust: not a B1 row
    add(c + 76, pooled, False, 2_000_000_000_000, 0.05)           # a pooled account is never a wallet
    add(c + 80, W[3], False, 2_000_000_000_000, 0.1)              # a sniper sells part of its bag
    for k in range(8):                                            # BOOST: 0.6 SOL every 12 s from g + 2
        add(g + 2 + 12 * k, W[30], True, 1_500_000_000_000, 0.6, VENUE_AMM)
    add(g + 5, W[31], True, 2_000_000_000_000, 0.8, VENUE_AMM)
    add(g + 40, W[0], False, 10_000_000_000_000, 0.5, VENUE_AMM)  # the creator sells into the pool
    add(g + 41, W[32], False, 300_000_000_000, 0.05, VENUE_AMM)   # a pool TRANSFEREE
    tr = FlowTracker("SYNTH", created_ts=c, creator=W[0], c_slot=c_slot, g_ts=g, history_from=c)
    tr.ingest(trades)
    tr.mark_complete(g + 400)
    for t in (c + 60, c + 100, g + 30, g + 60, g + 200):
        snap = tr.as_of(t)
        st = {"c_slot": c_slot, "c_ts": c, "vsol0": 30.0, "creator": W[0]}
        P = s1._build_prefix(snap.trades.reset_index(drop=True), st, float(g))
        roles = snap.roles()
        for name, mask in (("transferees", P.transferee_w), ("bundle", P.bundle_w), ("snipers", P.sniper_w),
                           ("insiders", P.ins_w)):
            assert {wallet_h(w) for w in roles[name]} == {int(h) for h in P.uw[mask]}, (t, name)
        assert {wallet_h(w) for w in roles["agent"]} == ({int(P.uw[P.agent_code])} if P.agent_code is not None
                                                         else set())
        ins = snap.inventory()["insiders"]
        assert ins["held_tok"] == pytest.approx(P.insider_hold, rel=1e-12)
        assert ins["peak_tok"] == pytest.approx(P.insider_peak, rel=1e-12)
        assert ins["cost_sol"] == pytest.approx(P.insider_cost_sol, rel=1e-9)
    last = tr.as_of(g + 200).roles()
    assert last["transferees"] == {W[27], W[28], W[32]} and W[30] in last["agent"]
    assert W[26] not in last["transferees"] and W[29] not in last["transferees"] and pooled not in last["insiders"]
