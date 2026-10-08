"""G1 (PLAN 4.2): a gate for factory, "completed" and operator coins -- when NOT to trade.

Research only (wave-2 lab). Nothing here is wired into the bot. Pre-registration: ``research/lab2/G1/PREREG.md``.

Every FEATURE comes from :class:`common.AsOf` (cutoff tau = t - 20 s; NULL stays None, never 0). Labels
(``dead60``, ``winner``) are outcomes: they are read through AsOf too, at the END of the coin's window, and are
never features.

What it measures
----------------
* **Classes** at g + 140 s (tau = g + 120 s, the PLAN's "g + 2 min"), in PLAN order:
  OPERATOR > FACTORY > COMPLETED > UNRESOLVED (a rule needs a NULL input) > ORGANIC. Two overlay flags:
  AIRDROP (the audit's airdrop dump, seen in completed bars) and SERIAL (the creator deployed >= 2 other
  graduates in the 24 h before tau). NEWS needs IPFS metadata we do not have: it is not computed.
* **Three gate variants** (PLAN 3.4 limit for G1 = 3): ``G-time`` (graduated <= 120 s after creation),
  ``G-chain`` (OPERATOR | FACTORY | COMPLETED), ``G-chain+`` (G-chain | AIRDROP | SERIAL). PLAN's G-full needs
  IPFS metadata (~27k fetches) and is replaced by G-chain+.
* **Two fixed hosts** whose losses per class are measured, each evaluated ungated and then gated as a veto on
  its trades (PLAN 3.5): ``G1.dip`` = the bot's CURRENT default dip-rebound (``src/nightcrawler`` StrategyParams
  defaults, re-implemented on AsOf bars; single full exit at +40 %), ``G1.R0`` = PLAN R0 random entries into alive
  coins (age >= 30 min, catastrophe stop -50 %, 60 min).

CLI::

    python research/lab2/g1.py --debug                       # census TRAIN third, counts only (no returns)
    python research/lab2/g1.py --stage train [--allow-partial]
    python research/lab2/g1.py --stage val
    LAB2_ALLOW_TEST=1 python research/lab2/g1.py --stage test
    LAB2_ALLOW_CONFIRM=1 python research/lab2/g1.py --stage confirm
    LAB2_ALLOW_FINAL=1 python research/lab2/g1.py --stage final
    python research/lab2/g1.py --stage val --check           # prerequisites only

Each stage writes ``G1/<stage>.json`` and ``G1/<stage>.md`` and refuses to run when its prerequisites are missing
(no VAL without a written shortlist, no TEST twice, never FINAL before TEST, no stage after a KILL, PLAN 8 data
gates V1-V4).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import common as C  # noqa: E402

OUT_DIR = HERE / "G1"
HYP, HYP_DIP, HYP_R0 = "G1", "G1.dip", "G1.R0"
VARIANTS = ("G-time", "G-chain", "G-chain+")
CHAIN_VARIANTS = ("G-chain", "G-chain+")
STAGES = ("train", "val", "test", "confirm", "final")
STAGE_SPLIT = {"train": "train", "val": "val", "test": "test", "confirm": "confirm", "final": "final",
               "debug": "final_train"}
STAGE_ENV = {"test": "LAB2_ALLOW_TEST", "confirm": "LAB2_ALLOW_CONFIRM", "final": "LAB2_ALLOW_FINAL"}
SHIP_VERDICTS = ("PASS_CHAIN", "SHIP_G_TIME")

# =========================================================================== pre-registered constants
# PLAN 4.2 class thresholds (fixed in advance from the launch sample's STRUCTURE, never its outcomes)
INSTANT_MAX_DELAY_S = 5.0
G_TIME_MAX_DELAY_S = 120.0
OPERATOR_MIN_BUY_SOL = 500.0
OPERATOR_MAX_BUYERS = 30
FACTORY_MIN_TOP5 = 0.85
COMPLETED_MIN_COMPLETER_SHARE = 0.6
COMPLETED_MIN_TOP3_SHARE = 0.6
COMPLETED_MIN_CURVE_BUYERS = 15         # COMPLETED if n_curve_buyers < 15
COMPLETER_WINDOW_SOL = 30.0             # completer_share = COMPLETER's SOL in the last 30 SOL / 30
CURVE_SUPPLY_TOK = 793.1e6              # bundle_share = creation-slot tokens / 793.1e6
TOP_K = 5
# additions asked for by the task, thresholds from AUDIT.md structure (2,200 equal transfers sold within 26 s;
# 1,545-2,149 never-bought sellers on factory coins vs 20-25 on organic ones), not from outcomes
AIRDROP_MIN_SELLS = 1000                # sell trades (dust included) in <= 2 consecutive completed clock minutes
AIRDROP_MIN_SELL_BUY_RATIO = 3.0        # ... with >= 3x as many sell trades as buy trades in those minutes
SERIAL_MIN_PRIOR = 2                    # creator deployed >= 2 OTHER graduates in the lookback before tau
REGISTRY_LOOKBACK_S = 86_400
REPEAT_MIN_COINS = 3                    # PLAN: top-5 pool buyer in the first 2 min of >= 3 earlier graduates
REGISTRY_WARM_MIN = 0.99                # share of lookback hours scanned for a "warm" registry
# labels (outcomes only)
LABEL_T_S = C.W120_S + C.DECISION_LAG_S  # 140 s
DEAD_LO_S, DEAD_HI_S, DEAD_MIN_USD = 3600, 4500, 100.0
WIN_REF_S, WIN_HORIZON_S, WIN_MULT = 900, 7200, 2.0
# decision bars (PLAN 4.2 pass; 3.5 veto bar reported alongside)
PREC_MIN, PREC_MIN_FLAGGED, MISSED_WIN_MAX, CHAIN_MARGIN = 0.90, 200, 0.05, 0.02
CONFIRM_PREC_MIN = 0.80                 # PLAN 4.2 live monitoring: disable below 80 % precision
MIN_CELL = 30                           # flagged and unflagged host trades needed for a sign / veto verdict

# The bot's CURRENT default dip-rebound (src/nightcrawler/models.py StrategyParams defaults; strategy.py
# entry_signal with snapshot=None, as research/lab/baseline.py runs it). Exit simplification: the bot sells 50 %
# at +40 % and trails the rest 15 %; the engine has no partial exits, so the whole position exits at +40 %.
DIP_PARAMS = {"host": "nightcrawler_dip_rebound_default", "dip_pct": 0.55, "confirm_green": 2, "dip_lookback_h": 6.0,
              "min_age_min": 60.0, "max_age_h": 48.0, "min_mcap_usd": 100_000.0, "max_mcap_usd": 5_000_000.0,
              "stop_pct": 0.18, "take_profit_pct": 0.40, "max_hold_min": 120.0}
# PLAN 4.1 R0: random entry into an alive coin aged >= 30 min, one per coin; exit = PLAN X1 exit 6 (catastrophe
# stop -50 % + 60 min) because X1's "best exit" does not exist yet.
R0_PARAMS = {"host": "R0_random_alive", "seed": 0, "age_lo_min": 30.0, "age_hi_min": 115.0,
             "alive_vol_usd_15m": 1500.0, "alive_mcap_usd": 6000.0, "stop_pct": 0.50, "max_hold_s": 3600.0}
STRESS = {"costs_x1.5": C.FillConfig().stressed(1.5), "rent_0.22": C.FillConfig(rent_usd=0.22),
          "alt_fill": C.FillConfig(entry_bar_exits=False, exit_delay_bars=1)}
DECL_HOST = {"uses_organic_flow": False, "uses_wallet_reputation": False, "uses_current_state_fields": False}
DECL_GATE = {"uses_organic_flow": False, "uses_wallet_reputation": True, "reputation_excludes_traded_coin": True,
             "uses_current_state_fields": False}


class G1Refused(RuntimeError):
    """A stage was asked for while its prerequisites are missing (or a stop rule fired)."""


# =========================================================================== None-safe logic (NULL is never 0)


def _nz(v: Any) -> Any:
    return None if v is None or (isinstance(v, str) and not v.strip()) else v


def _ge(x, t):
    return None if x is None else bool(x >= t)


def _le(x, t):
    return None if x is None else bool(x <= t)


def _lt(x, t):
    return None if x is None else bool(x < t)


def _any(*v) -> bool | None:
    if any(x is True for x in v):
        return True
    return None if any(x is None for x in v) else False


def _all(*v) -> bool | None:
    if any(x is False for x in v):
        return False
    return None if any(x is None for x in v) else True


def _ratio(a, b) -> float | None:
    if a is None or b is None or b <= 0:
        return None
    return float(a) / float(b)


def _delay_le(d: float | None, lb: float | None, x: float) -> bool | None:
    """grad_delay <= x. Exact when the creation is known; when it is not, the lower bound decides only if > x."""
    if d is not None:
        return bool(d <= x)
    if lb is not None and lb > x:
        return False
    return None


# =========================================================================== registry (cross-coin, causal)


@dataclass
class Registry:
    """Other graduates' creators and first-2-min top-5 pool buyers, each read through AsOf at its legal time.

    Events: (time the fact became knowable, mint). A query at tau uses events with tau - lookback < e <= tau from
    OTHER coins only (PLAN 6.6 rules 1, 4, 5). Pool: every graduate (any quote / Mayhem) created before the end
    of the split being run, so later splits never feed an earlier one."""

    creator_ev: dict[str, tuple[np.ndarray, tuple[str, ...]]] = field(default_factory=dict)
    wallet_ev: dict[str, tuple[np.ndarray, tuple[str, ...]]] = field(default_factory=dict)
    scanned_hours: np.ndarray = field(default_factory=lambda: np.zeros(0, np.int64))
    lookback_s: float = REGISTRY_LOOKBACK_S
    n_coins: int = 0

    @classmethod
    def from_coins(cls, coins: Iterable[C.CoinData], scanned_hours: Iterable[int],
                   lookback_s: float = REGISTRY_LOOKBACK_S) -> "Registry":
        cre: dict[str, list] = defaultdict(list)
        wal: dict[str, list] = defaultdict(list)
        n = 0
        for cd in coins:
            n += 1
            s = C.AsOf(cd, cd.g + C.DECISION_LAG_S)          # tau = g: the coin is a graduate from now on
            cr = _nz(s.get("creator"))
            if cr is not None:
                cre[cr].append((cd.g, cd.mint))
            for tau in (cd.g + C.W120_S, cd.g + C.AGENT_WINDOW_S):
                s2 = C.AsOf(cd, tau + C.DECISION_LAG_S)
                if not s2.agent_resolved:
                    continue
                try:
                    lst = s2.top_buyers("w120", exclude_agent=True)
                except C.NotYetKnown:
                    continue
                for w in sorted(lst or (), key=lambda w: -float(w[1]))[:TOP_K]:
                    if float(w[1]) > 0:
                        wal[w[0]].append((float(tau), cd.mint))
                break

        def pack(d):
            out = {}
            for k, ev in d.items():
                ev.sort()
                out[k] = (np.array([e[0] for e in ev], float), tuple(e[1] for e in ev))
            return out
        hrs = np.array(sorted(set(int(h) for h in scanned_hours)), np.int64)
        return cls(creator_ev=pack(cre), wallet_ev=pack(wal), scanned_hours=hrs, lookback_s=lookback_s, n_coins=n)

    def _count(self, table: dict, key: str, tau: float, mint: str) -> int:
        ev = table.get(key)
        if ev is None:
            return 0
        ts, mints = ev
        lo = int(np.searchsorted(ts, tau - self.lookback_s, side="right"))
        hi = int(np.searchsorted(ts, tau, side="right"))
        return len({m for m in mints[lo:hi] if m != mint})

    def serial_prior(self, creator: str, tau: float, mint: str) -> int:
        """Other graduates of ``creator`` known (graduated) in (tau - lookback, tau]."""
        return self._count(self.creator_ev, creator, tau, mint)

    def wallet_prior(self, wallet: str, tau: float, mint: str) -> int:
        """Other graduates where ``wallet`` was a top-5 pool buyer of the first 2 min, known in (tau - lookback, tau]."""
        return self._count(self.wallet_ev, wallet, tau, mint)

    def coverage(self, tau: float) -> float:
        """Share of the lookback's whole hours that were scanned (backfill coverage of the registry)."""
        n_h = int(self.lookback_s // 3600)
        hi = int(tau) // 3600 * 3600
        want = np.arange(hi - 3600 * n_h, hi, 3600, dtype=np.int64)
        if not len(want):
            return 1.0
        return float(np.isin(want, self.scanned_hours).mean())

    def repeat_share(self, snap: C.AsOf, denom: float | None) -> float | None:
        """PLAN repeat_migbuyer_share_2m: w120 buy SOL of repeat migration buyers / amm_buy_sol_2m (lower bound:
        only the stored top-10 list is visible)."""
        if denom is None or denom <= 0:
            return None
        try:
            lst = snap.top_buyers("w120", exclude_agent=snap.agent_resolved)
        except C.NotYetKnown:
            return None
        if lst is None:
            return None
        sol = sum(float(w[1]) for w in lst if self.wallet_prior(w[0], snap.tau, snap.mint) >= REPEAT_MIN_COINS)
        return float(sol / denom)


def _split_hi(split: str, census: C.Census) -> float:
    if split in C.SPLIT_BOUNDS:
        return float(C.SPLIT_BOUNDS[split][1])
    if split == "final_train":
        return float(census.train_hi) + 1.0
    if split == "final_val":
        return float(census.val_hi) + 1.0
    return math.inf


def registry_from_frames(graduates: pd.DataFrame, b2_coins: pd.DataFrame, split: str, census: C.Census,
                         lookback_s: float = REGISTRY_LOOKBACK_S, g_min: float | None = None) -> Registry:
    """Registry pool = every graduate created before the end of ``split`` (and graduated after ``g_min``)."""
    g = C._normalize_graduates(graduates, census)
    hours = set((graduates["g_ts"].to_numpy(np.int64) // 3600 * 3600).tolist()) if len(graduates) else set()
    keep = g["created_for_split"] < _split_hi(split, census)
    if g_min is not None:
        keep &= g["g_ts"] >= g_min
    g = g[keep]
    b2c = b2_coins.drop(columns=[c for c in ("g_ts", "grad_delay_s", "sol_quoted", "mayhem") if c in b2_coins])
    m = g.merge(b2c, on=["mint", "pool"], how="left")
    pooled = set(C.POOLED_ACCOUNTS) | C._pooled_from_file()
    empty = pd.DataFrame(columns=["minute_ts", "open", "high", "low", "close", "x_close", "y_close"])
    coins = (C._make_coin(r, empty, None, pooled) for r in m.to_dict("records"))
    return Registry.from_coins(coins, hours, lookback_s)


def registry_for(ds: C.Dataset, frames: tuple | None = None, census: C.Census | None = None,
                 flow: Path | None = None) -> Registry:
    census = census if census is not None else C.Census.load()
    if frames is None:
        f = flow or C.flow_dir()
        frames = (C._read_parquet(f / "graduates.parquet"), C._read_parquet(f / "b2_coins.parquet"))
    g_min = float(ds.coins["g_ts"].min()) - REGISTRY_LOOKBACK_S - 3600 if len(ds) else None
    return registry_from_frames(frames[0], frames[1], ds.split, census, g_min=g_min)


# =========================================================================== features (AsOf only)


def airdrop_dump(snap: C.AsOf) -> dict:
    """The audit's airdrop dump as seen in COMPLETED minute bars: >= 1000 sell trades within <= 2 consecutive
    clock minutes, >= 3x the buy trades there. (The equal-amount transfers themselves need token_transfers.)"""
    b = snap.bars
    ns = np.asarray(b.n_sells, float)
    nb = np.asarray(b.n_buys, float)
    k = len(ns)
    if k == 0:
        return {"airdrop_seen": False, "airdrop_age_s": None, "airdrop_max_sells_2m": 0.0}
    s2, b2 = ns.copy(), nb.copy()
    s2[:-1] += ns[1:]
    b2[:-1] += nb[1:]
    hit = (s2 >= AIRDROP_MIN_SELLS) & (s2 >= AIRDROP_MIN_SELL_BUY_RATIO * b2)
    if hit.any():
        j = int(np.argmax(hit))
        end = int(b.minute_ts[min(j + 1, k - 1)]) + 60
        return {"airdrop_seen": True, "airdrop_age_s": float(end - snap.g), "airdrop_max_sells_2m": float(s2.max())}
    return {"airdrop_seen": False, "airdrop_age_s": None, "airdrop_max_sells_2m": float(s2.max())}


def g1_features(snap: C.AsOf, reg: Registry | None = None) -> dict[str, Any]:
    """Every G1 feature at ``snap.tau`` (None = unknown / NULL / not yet legal)."""
    f: dict[str, Any] = {"t": snap.t, "tau": snap.tau, "age_s": snap.age_s}
    d, lb = snap.get("grad_delay_s"), snap.get("grad_delay_lb_s")
    f["grad_delay_s"], f["grad_delay_lb_s"] = d, lb
    f["instant"] = _delay_le(d, lb, INSTANT_MAX_DELAY_S)
    f["fast120"] = _delay_le(d, lb, G_TIME_MAX_DELAY_S)
    # curve phase (known at g; NULL without creation data)
    zt = snap.get("z_buy_tok")
    f["bundle_share"] = None if zt is None else float(zt) / CURVE_SUPPLY_TOK
    zn, znc = snap.get("z_n_buyers"), snap.get("z_n_buyers_noncreator")
    f["creator_in_bundle"] = None if zn is None or znc is None else bool(zn > znc)
    cb = snap.get("curve_buy_sol")
    f["curve_top1_share"] = _ratio(snap.get("curve_top1_buy_sol"), cb)
    f["curve_top3_share"] = _ratio(snap.get("curve_top3_buy_sol"), cb)
    cs = snap.get("completer_sol")
    f["completer_share"] = None if cs is None else float(cs) / COMPLETER_WINDOW_SOL
    f["n_curve_buyers"] = snap.get("curve_n_buyers")
    # pool, first 120 s (legal from tau >= g + 120)
    wb, ws, nb = snap.get("w120_buy_sol"), snap.get("w120_sell_sol"), snap.get("w120_n_buyers")
    raw = snap.get("w120_top10")
    det = snap.agent_detected
    aw = _nz(snap.get("agent_wallet")) if det else None
    a_sol = sum(float(w[1]) for w in raw if w[0] == aw) if (raw and aw) else 0.0
    off = snap.get("agent_first_offset_s") if det else None
    a_buyer = 1 if (det and off is not None and off < C.W120_S) else 0
    f["amm_buy_sol_2m"] = None if wb is None else float(wb) - a_sol
    f["amm_buyers_2m"] = None if nb is None else max(int(nb) - a_buyer, 0)
    f["amm_sell_buy_2m"] = _ratio(ws, wb)
    try:
        f["amm_top5_share_2m"] = None if wb is None else snap.top_share("w120", TOP_K, exclude_agent=snap.agent_resolved)
    except C.NotYetKnown:
        f["amm_top5_share_2m"] = None
    f["agent_present"] = det
    f["agent_resolved"] = snap.agent_resolved
    f.update(airdrop_dump(snap))
    cr = _nz(snap.get("creator"))
    f["creator_known"] = cr is not None
    if reg is not None:
        f["serial_prior"] = None if cr is None else reg.serial_prior(cr, snap.tau, snap.mint)
        f["registry_cov"] = reg.coverage(snap.tau)
        f["repeat_migbuyer_share_2m"] = reg.repeat_share(snap, f["amm_buy_sol_2m"])
    else:
        f["serial_prior"] = f["registry_cov"] = f["repeat_migbuyer_share_2m"] = None
    f["serial"] = None if f["serial_prior"] is None else bool(f["serial_prior"] >= SERIAL_MIN_PRIOR)
    uri = _nz(snap.get("uri"))
    f["uri_host"] = None if uri is None else (uri.split("/")[2] if "//" in uri else uri[:16])
    return f


def classify(f: Mapping[str, Any]) -> dict[str, Any]:
    """PLAN 4.2 classes in order, overlay flags, and each variant's gate set (skip) and dead set (precision)."""
    op = _all(_ge(f.get("amm_buy_sol_2m"), OPERATOR_MIN_BUY_SOL), _le(f.get("amm_buyers_2m"), OPERATOR_MAX_BUYERS))
    inst = f.get("instant")
    fa = _all(inst, _ge(f.get("amm_top5_share_2m"), FACTORY_MIN_TOP5))
    not_inst = None if inst is None else (not inst)
    co = _all(not_inst, _any(_ge(f.get("completer_share"), COMPLETED_MIN_COMPLETER_SHARE),
                             _ge(f.get("curve_top3_share"), COMPLETED_MIN_TOP3_SHARE),
                             _lt(f.get("n_curve_buyers"), COMPLETED_MIN_CURVE_BUYERS)))
    if op is True:
        cls = "OPERATOR"
    elif fa is True:
        cls = "FACTORY"
    elif co is True:
        cls = "COMPLETED"
    elif op is None or fa is None or co is None:
        cls = "UNRESOLVED"
    else:
        cls = "ORGANIC"
    airdrop = f.get("airdrop_seen") is True
    serial = f.get("serial") is True
    chain = cls in ("OPERATOR", "FACTORY", "COMPLETED")
    dead_chain = cls in ("FACTORY", "COMPLETED")
    flag = {"G-time": f.get("fast120") is True, "G-chain": chain, "G-chain+": chain or airdrop or serial}
    dead = {"G-time": flag["G-time"], "G-chain": dead_chain, "G-chain+": dead_chain or airdrop or serial}
    return {"g1_class": cls, "operator": op, "factory": fa, "completed": co, "airdrop": airdrop, "serial": serial,
            "flag": flag, "dead": dead}


# =========================================================================== hosts (fixed, not searched)


def _creation_age_s(snap: C.AsOf) -> tuple[float, bool]:
    """Age since creation at t: exact, or a lower bound (graduation age + the creation lower bound)."""
    c = snap.get("created_ts")
    if c is not None:
        return snap.t - float(c), True
    lb = snap.get("grad_delay_lb_s")
    return snap.age_s + float(lb if lb is not None else C.SLOW_CREATE_LOOKBACK_S), False


def dip_signal(bars: C.Bars, p: Mapping[str, Any]) -> bool:
    """nightcrawler.strategy.entry_signal (snapshot=None) on completed TRADED minutes (feeds omit empty minutes).
    The 6 h lookback covers every bar we have (the window is 180 min)."""
    tr = np.asarray(bars.traded, float) > 0
    o, h, l, c = (np.asarray(getattr(bars, k))[tr] for k in ("o", "h", "l", "c"))
    v = (np.asarray(bars.buy_sol) + np.asarray(bars.sell_sol))[tr]
    if len(c) < int(p["confirm_green"]) + 2:
        return False
    i_high = int(np.argmax(h))
    high = float(h[i_high])
    dip = 1.0 - float(l[i_high + 1:].min()) / high if i_high + 1 < len(c) and high > 0 else 0.0
    if dip < p["dip_pct"]:
        return False
    if c[-1] > high * (1.0 - p["dip_pct"] / 2):
        return False
    run = 0
    for i in range(len(c) - 1, -1, -1):
        if not c[i] > o[i]:
            break
        run += 1
    if run < int(p["confirm_green"]):
        return False
    return bool(c[-1] > h[-2] or v[-1] > v[-2])


def dip_universe_ok(snap: C.AsOf, p: Mapping[str, Any] = DIP_PARAMS) -> bool:
    age, _ = _creation_age_s(snap)
    return age >= p["min_age_min"] * 60 and p["min_mcap_usd"] <= snap.mcap_usd <= p["max_mcap_usd"]


def host_dip(snap: C.AsOf, p: Mapping[str, Any], pos: C.PositionView | None):
    if pos is not None:
        return None                     # mechanical exits only (stop 18 %, take-profit +40 %, 120 min)
    age, _ = _creation_age_s(snap)
    if age > p["max_age_h"] * 3600:
        return C.SKIP
    if age < p["min_age_min"] * 60:
        return None
    if not p["min_mcap_usd"] <= snap.mcap_usd <= p["max_mcap_usd"]:
        return None
    if not dip_signal(snap.bars, p):
        return None
    return C.Enter(exits=C.ExitSpec(stop_pct=p["stop_pct"], take_profit_pct=p["take_profit_pct"],
                                    max_hold_s=p["max_hold_min"] * 60), tag="dip")


def r0_target_age_s(mint: str, p: Mapping[str, Any]) -> float:
    h = int(hashlib.sha256(f"{p['seed']}:{mint}".encode()).hexdigest()[:12], 16) / float(16 ** 12)
    return 60.0 * (p["age_lo_min"] + h * (p["age_hi_min"] - p["age_lo_min"]))


def host_r0(snap: C.AsOf, p: Mapping[str, Any], pos: C.PositionView | None):
    """PLAN R0: at a seeded random age in [30, 115] min, enter if the coin is alive, else never."""
    if pos is not None:
        return None
    if snap.age_s < r0_target_age_s(snap.mint, p):
        return None
    if snap.alive(p["alive_vol_usd_15m"], p["alive_mcap_usd"]):
        return C.Enter(exits=C.ExitSpec(stop_pct=p["stop_pct"], max_hold_s=p["max_hold_s"]), tag="R0")
    return C.SKIP


HOSTS = {"dip": (HYP_DIP, host_dip, DIP_PARAMS), "R0": (HYP_R0, host_r0, R0_PARAMS)}


# =========================================================================== labels (outcomes) and tables


def coin_labels(cd: C.CoinData, sol: C.SolUsd) -> dict:
    """dead60: no minute with >= $100 volume in [g + 60, g + 75) min. winner: a high >= 2x the price at g + 15 min
    within the next 2 h. Read through AsOf at the window's end: OUTCOMES, never features."""
    s_end = C.AsOf(cd, cd.m0 + 60 * C.N_BARS + C.DECISION_LAG_S, sol)
    b = s_end.bars
    mt = np.asarray(b.minute_ts, float)
    vol = np.asarray(b.buy_sol) + np.asarray(b.sell_sol)
    sel = np.where((mt >= cd.g + DEAD_LO_S) & (mt < cd.g + DEAD_HI_S))[0]
    usd = [vol[i] * sol.at(mt[i]) for i in sel]
    dead60 = not any(u >= DEAD_MIN_USD for u in usd)
    s15 = C.AsOf(cd, cd.g + WIN_REF_S + C.DECISION_LAG_S, sol)
    p15 = s15.price
    after = (mt + 60 > s15.tau) & (mt + 60 <= cd.g + WIN_REF_S + WIN_HORIZON_S)
    hi = float(np.asarray(b.h)[after].max()) if after.any() else p15
    ad = airdrop_dump(s_end)
    return {"dead60": bool(dead60), "winner": bool(hi >= WIN_MULT * p15), "airdrop_by_end": ad["airdrop_seen"],
            "airdrop_age_s": ad["airdrop_age_s"]}


FEATURE_COLS = ("grad_delay_s", "instant", "fast120", "bundle_share", "creator_in_bundle", "curve_top1_share",
                "curve_top3_share", "completer_share", "n_curve_buyers", "amm_buy_sol_2m", "amm_buyers_2m",
                "amm_sell_buy_2m", "amm_top5_share_2m", "agent_present", "airdrop_seen", "serial_prior", "serial",
                "registry_cov", "repeat_migbuyer_share_2m", "creator_known", "uri_host")


GATE_COLS = (list(FEATURE_COLS) + ["g1_class", "airdrop", "serial_flag"] + [f"flag_{v}" for v in VARIANTS]
             + [f"dead_{v}" for v in VARIANTS])


def _gate_cols(f: Mapping, c: Mapping) -> dict:
    out = {k: f.get(k) for k in FEATURE_COLS}
    out.update({"g1_class": c["g1_class"], "airdrop": c["airdrop"], "serial_flag": c["serial"]})
    for v in VARIANTS:
        out[f"flag_{v}"] = c["flag"][v]
        out[f"dead_{v}"] = c["dead"][v]
    return out


def coin_table(ds: C.Dataset, reg: Registry, labels: bool = True) -> pd.DataFrame:
    """One row per usable coin: classes at g + 140 s, and (optionally) the outcome labels."""
    created = dict(zip(ds.coins["mint"], ds.coins["created_for_split"].astype(float)))
    rows = []
    for m in ds.mints:
        cd = ds.coin(m)
        f = g1_features(ds.asof(m, cd.g + LABEL_T_S), reg)
        row = {"mint": m, "g_ts": cd.g, "created_for_split": created[m]}
        row.update(_gate_cols(f, classify(f)))
        if labels:
            row.update(coin_labels(cd, ds.sol))
        rows.append(row)
    cols = ["mint", "g_ts", "created_for_split"] + GATE_COLS + (
        ["dead60", "winner", "airdrop_by_end", "airdrop_age_s"] if labels else [])
    return pd.DataFrame(rows, columns=cols)


def annotate(trades: pd.DataFrame, ds: C.Dataset, reg: Registry) -> pd.DataFrame:
    """Host trades + the gate's view AT THE DECISION TIME (exactly what a live gate would see then)."""
    rows = []
    for r in trades.itertuples(index=False):
        f = g1_features(ds.asof(r.mint, r.t_dec), reg)
        rows.append(_gate_cols(f, classify(f)))
    extra = pd.DataFrame(rows, columns=GATE_COLS, index=trades.index)
    return pd.concat([trades, extra], axis=1)


# =========================================================================== statistics


def _cell(t: pd.DataFrame, B: int, hide: bool, size_usd: float = 20.0) -> dict:
    n = int(len(t))
    out: dict[str, Any] = {"n": n, "n_coins": int(t["mint"].nunique()) if n else 0}
    if hide or n == 0:
        return out
    d = C.describe(t, B=B)
    out.update({k: d.get(k) for k in ("mean", "median", "win_rate", "ci90", "ci95", "mean_without_top2",
                                       "top_coin_share")})
    out["pnl_usd"] = float(t["ret_net"].sum() * size_usd)
    return out


def boot_subset_diff(r: np.ndarray, coins: np.ndarray, a: np.ndarray, b: np.ndarray, B: int = 10_000,
                     seed: int = 0) -> tuple[float | None, tuple[float, float] | None]:
    """mean(r | a) - mean(r | b) with a coin-cluster bootstrap 95 % CI (``a`` and ``b`` may overlap)."""
    r = np.asarray(r, float)
    a, b = np.asarray(a, bool), np.asarray(b, bool)
    if not a.any() or not b.any():
        return None, None
    diff = float(r[a].mean() - r[b].mean())
    codes, _ = pd.factorize(pd.Series(list(coins)))
    n = int(codes.max()) + 1
    if n < 2:
        return diff, None
    sa = np.bincount(codes, weights=r * a, minlength=n)
    ca = np.bincount(codes, weights=a.astype(float), minlength=n)
    sb = np.bincount(codes, weights=r * b, minlength=n)
    cb = np.bincount(codes, weights=b.astype(float), minlength=n)
    rng = np.random.default_rng(seed)
    out = []
    step = max(1, int(2_000_000 // n))
    for s in range(0, B, step):
        idx = rng.integers(0, n, size=(min(B, s + step) - s, n))
        na, nb = ca[idx].sum(1), cb[idx].sum(1)
        ok = (na > 0) & (nb > 0)
        out.append(sa[idx].sum(1)[ok] / na[ok] - sb[idx].sum(1)[ok] / nb[ok])
    d = np.concatenate(out)
    if not len(d):
        return diff, None
    return diff, (float(np.quantile(d, 0.025)), float(np.quantile(d, 0.975)))


def eval_variants(variants: Iterable[str], coins_df: pd.DataFrame, host_trades: Mapping[str, pd.DataFrame], *,
                  B: int = 10_000, hide: bool = False, n_trials_total: int | None = None) -> dict:
    """Per variant: label precision for dead60 and missed winners (PLAN 4.2), and per host the flagged vs
    unflagged returns, the 3.5 veto bar, and the gated host. Plus chain vs time on R0's unflagged set."""
    variants = list(variants)
    out: dict[str, Any] = {}
    for v in variants:
        dv = coins_df[f"dead_{v}"].to_numpy(bool) if len(coins_df) else np.zeros(0, bool)
        fv = coins_df[f"flag_{v}"].to_numpy(bool) if len(coins_df) else np.zeros(0, bool)
        lab: dict[str, Any] = {"n_coins": int(len(coins_df)), "n_flag_gate": int(fv.sum()), "n_flag_dead": int(dv.sum())}
        if not hide and len(coins_df) and "dead60" in coins_df:
            dead = coins_df["dead60"].to_numpy(bool)
            win = coins_df["winner"].to_numpy(bool)
            lab.update({
                "dead60_base_rate": float(dead.mean()),
                "precision_dead60": float(dead[dv].mean()) if dv.any() else None,
                "dead60_recall": float(dv[dead].mean()) if dead.any() else None,
                "missed_winner_rate": float(win[dv].mean()) if dv.any() else None,
                "winners_lost_share": float(dv[win].mean()) if win.any() else None,
                "n_winners": int(win.sum()),
            })
        hosts = {}
        for h, t in host_trades.items():
            fl = t[f"flag_{v}"].to_numpy(bool) if len(t) else np.zeros(0, bool)
            cell: dict[str, Any] = {"flagged": _cell(t[fl], B, hide), "unflagged": _cell(t[~fl], B, hide)}
            if not hide and len(t):
                r = t["ret_net"].to_numpy(float)
                coins = t["mint"].to_numpy(object)
                diff, ci = boot_subset_diff(r, coins, fl, ~fl, B)
                cell["diff_flagged_minus_unflagged"] = diff
                cell["diff_ci95"] = ci
                wins = r[r > 0].sum()
                cell["winning_profit_removed"] = float(r[fl & (r > 0)].sum() / wins) if wins > 0 else None
                cell["pnl_usd"] = {"host": float(r.sum() * 20), "gated": float(r[~fl].sum() * 20)}
                cell["veto_3_5"] = C.verdict_veto(t, fl, B=min(B, 4000))
                g = t[~fl]
                cell["gated"] = C.describe(g, B=B, n_trials_total=n_trials_total) if len(g) else {"n": 0}
                cell["gated"].pop("reasons", None)
                cell["gated_auto_rejections_3_6"] = C.auto_rejections(C.Result(
                    trades=g, placebo=pd.DataFrame(), stress={}, meta={"declarations": DECL_GATE}))
                if v == "G-chain+" and "registry_cov" in t:   # PLAN 6.6 rule 8: with / without a cold registry
                    warm = t["registry_cov"].fillna(0).to_numpy(float) >= REGISTRY_WARM_MIN
                    d_w, ci_w = boot_subset_diff(r[warm], coins[warm], fl[warm], ~fl[warm], B) if warm.any() else (None, None)
                    cell["warm_registry_only"] = {"n": int(warm.sum()), "n_flagged": int((fl & warm).sum()),
                                                  "diff_flagged_minus_unflagged": d_w, "diff_ci95": ci_w}
            hosts[h] = cell
        out[v] = {"labels": lab, "hosts": hosts}
    cmp: dict[str, Any] = {}
    if "G-time" in variants and not hide and "R0" in host_trades and len(host_trades["R0"]):
        t = host_trades["R0"]
        r, coins = t["ret_net"].to_numpy(float), t["mint"].to_numpy(object)
        base = ~t["flag_G-time"].to_numpy(bool)
        for v in variants:
            if v == "G-time":
                continue
            keep = ~t[f"flag_{v}"].to_numpy(bool)
            diff, ci = boot_subset_diff(r, coins, keep, base, B, seed=1)
            cmp[v] = {"r0_unflagged_mean_minus_g_time": diff, "ci95": ci, "n_unflagged": int(keep.sum()),
                      "n_unflagged_g_time": int(base.sum())}
    out["_chain_vs_time_R0"] = cmp
    return out


def class_tables(coins_df: pd.DataFrame, host_trades: Mapping[str, pd.DataFrame], *, B: int = 2000,
                 hide: bool = False) -> dict:
    """How much each class loses: per exclusive class and per overlay flag, for the coins (labels) and each host."""
    out: dict[str, Any] = {"coins": {}, "hosts": {}}
    groups = ["OPERATOR", "FACTORY", "COMPLETED", "UNRESOLVED", "ORGANIC"]
    if len(coins_df):
        for cls in groups:
            sub = coins_df[coins_df["g1_class"] == cls]
            cell: dict[str, Any] = {"n_coins": int(len(sub))}
            if not hide and len(sub) and "dead60" in sub:
                cell.update({"dead60_rate": float(sub["dead60"].mean()), "winner_rate": float(sub["winner"].mean()),
                             "airdrop_by_end_rate": float(sub["airdrop_by_end"].mean())})
            elif "airdrop_by_end" in sub:
                cell["n_airdrop_by_end"] = int(sub["airdrop_by_end"].sum())
            out["coins"][cls] = cell
        for name, col in (("SERIAL", "serial_flag"), ("INSTANT", "instant"), ("FAST120", "fast120")):
            sub = coins_df[coins_df[col].map(lambda x: x is True or x is np.True_).to_numpy(bool)]
            cell = {"n_coins": int(len(sub))}
            if not hide and len(sub) and "dead60" in sub:
                cell.update({"dead60_rate": float(sub["dead60"].mean()), "winner_rate": float(sub["winner"].mean())})
            out["coins"]["flag:" + name] = cell
    for h, t in host_trades.items():
        tab: dict[str, Any] = {}
        for cls in groups:
            tab[cls] = _cell(t[t["g1_class"] == cls], B, hide) if len(t) else {"n": 0}
        if len(t):
            for name, col in (("AIRDROP", "airdrop"), ("SERIAL", "serial_flag"), ("INSTANT", "instant"),
                              ("FAST120", "fast120")):
                m = t[col].map(lambda x: x is True or x is np.True_).to_numpy(bool)
                tab["flag:" + name] = _cell(t[m], B, hide)
                tab["noflag:" + name] = _cell(t[~m], B, hide)
            if not hide:
                tot = float(t["ret_net"].sum() * 20)
                tab["_share_of_host_pnl"] = {cls: (float(t.loc[t["g1_class"] == cls, "ret_net"].sum() * 20) / tot
                                                   if tot else None) for cls in groups}
                tab["_host_pnl_usd"] = tot
        out["hosts"][h] = tab
    return out


def host_report(res: C.Result, B: int, hide: bool, n_trials_total: int | None) -> dict:
    t = res.trades
    out: dict[str, Any] = {"hypothesis": res.meta["hypothesis"], "params": res.meta["params"],
                           "config": res.meta.get("config"), "n": int(len(t)),
                           "n_coins": int(t["mint"].nunique()) if len(t) else 0,
                           "n_placebo": int(len(res.placebo)),
                           "reasons": t["reason"].value_counts().to_dict() if len(t) else {},
                           "auto_rejections_3_6": C.auto_rejections(res)}
    if hide:
        out["returns"] = "hidden (debug split: never choose parameters on FINAL data)"
        return out
    out["summary"] = C.describe(t, B=B, n_trials_total=n_trials_total)
    out["placebo"] = C.placebo_compare(t, res.placebo, B=B) if len(res.placebo) and len(t) else None
    out["stress"] = {k: {kk: vv for kk, vv in C.describe(v, B=min(B, 2000)).items()
                         if kk in ("n", "mean", "median", "ci95")} for k, v in res.stress.items()}
    out["portfolio"] = {k: v for k, v in C.portfolio_sim(t).items() if k != "skipped_mints"}
    return out


# =========================================================================== decisions (pre-registered rules)


def shortlist_rule(ev: Mapping[str, Any]) -> list[dict]:
    """TRAIN -> VAL shortlist: G-time (the PLAN fallback) + the chain variant with the higher mean net return of
    R0 trades it keeps; a tie (or no data) picks the simpler G-chain."""
    def kept_mean(v):
        try:
            return ev[v]["hosts"]["R0"]["unflagged"].get("mean")
        except KeyError:
            return None
    a, b = kept_mean("G-chain"), kept_mean("G-chain+")
    best = "G-chain+" if (b is not None and (a is None or b > a)) else "G-chain"
    return [{"gate": "G-time"}, {"gate": best}]


def decide_val(ev: Mapping[str, Any], shortlist: list[dict]) -> dict:
    """PLAN 4.2 pass on VAL. c1: dead-set precision >= 90 % with >= 200 coins flagged; c2: missed winners
    <= 5 %; c3: the chain variant beats G-time by >= 2 points per R0 trade on the unflagged set, 95 % CI > 0.
    c1 & c2 & c3 -> PASS_CHAIN (ship the chain variant); c1 & c2 -> SHIP_G_TIME; < 200 flagged -> UNDERPOWERED;
    else KILL. Only PASS_CHAIN / SHIP_G_TIME open TEST."""
    chain = [c["gate"] for c in shortlist if c["gate"] != "G-time"]
    v = chain[0] if chain else None
    if v is None or v not in ev:
        return {"verdict": "KILL", "reason": "no chain variant evaluated on VAL", "ship": None}
    lab = ev[v]["labels"]
    prec, n_dead, miss = lab.get("precision_dead60"), lab.get("n_flag_dead", 0), lab.get("missed_winner_rate")
    cmp = (ev.get("_chain_vs_time_R0") or {}).get(v) or {}
    diff, ci = cmp.get("r0_unflagged_mean_minus_g_time"), cmp.get("ci95")
    c1 = prec is not None and prec >= PREC_MIN and n_dead >= PREC_MIN_FLAGGED
    c2 = miss is not None and miss <= MISSED_WIN_MAX
    c3 = diff is not None and ci is not None and diff >= CHAIN_MARGIN and ci[0] > 0
    crit = {"c1_precision": {"value": prec, "n_flagged": n_dead, "need": f">= {PREC_MIN} with >= {PREC_MIN_FLAGGED}",
                             "pass": c1},
            "c2_missed_winners": {"value": miss, "need": f"<= {MISSED_WIN_MAX}", "pass": c2},
            "c3_chain_beats_time_R0": {"value": diff, "ci95": ci, "need": f">= {CHAIN_MARGIN}, CI > 0", "pass": c3}}
    if n_dead < PREC_MIN_FLAGGED:
        verdict, ship = "UNDERPOWERED", None
    elif c1 and c2 and c3:
        verdict, ship = "PASS_CHAIN", v
    elif c1 and c2:
        verdict, ship = "SHIP_G_TIME", "G-time"
    else:
        verdict, ship = "KILL", None
    return {"verdict": verdict, "ship": ship, "chain_variant": v, "criteria": crit}


def decide_confirm(ev: Mapping[str, Any], v: str) -> dict:
    """TEST / CONFIRM / FINAL check of the shipped variant: dead-set precision >= 80 % (PLAN live floor) and R0
    flagged trades worse than unflagged ones (same sign as VAL). UNDERPOWERED below 30 trades on either side."""
    lab = ev[v]["labels"]
    r0 = ev[v]["hosts"].get("R0", {})
    nf, nu = r0.get("flagged", {}).get("n", 0), r0.get("unflagged", {}).get("n", 0)
    prec, diff = lab.get("precision_dead60"), r0.get("diff_flagged_minus_unflagged")
    ok_prec = prec is not None and prec >= CONFIRM_PREC_MIN
    ok_sign = diff is not None and diff < 0
    if nf < MIN_CELL or nu < MIN_CELL:
        verdict = "UNDERPOWERED"
    else:
        verdict = "CONFIRMED" if ok_prec and ok_sign else "NOT_CONFIRMED"
    return {"verdict": verdict, "variant": v, "precision_dead60": prec, "precision_ok": ok_prec,
            "r0_flagged_minus_unflagged": diff, "ci95": r0.get("diff_ci95"), "sign_ok": ok_sign,
            "r0_n_flagged": nf, "r0_n_unflagged": nu}


# =========================================================================== prerequisites and stop rules


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _read_json(p: Path) -> dict | None:
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return None


def data_gates(flow: Path | None = None) -> tuple[bool, list[str]]:
    """PLAN 8 rule 1 (data first): V1 labels, V2 reserve chain >= 99 %, V3 cross-source >= 95 %, V4 ordering."""
    v = _read_json((flow or C.flow_dir()) / "validation.json")
    if v is None:
        return False, ["FLOW/validation.json missing: run research/flow/validate.py first"]
    bad = []
    try:
        if not v["V1"].get("pass"):
            bad.append("V1 labels failed")
        if v["V2"]["chain_ok"] / max(v["V2"]["transitions"], 1) < 0.99:
            bad.append("V2 reserve chain < 99 %")
        if v["V3"]["both"] / max(v["V3"]["coin_windows"], 1) < 0.95:
            bad.append("V3 cross-source < 95 %")
        if not v["V4"].get("pass"):
            bad.append("V4 ordering failed")
    except (KeyError, TypeError) as e:
        bad.append(f"validation.json unreadable: {e!r}")
    return not bad, bad


def coverage_check(cov: Mapping[str, Any]) -> tuple[bool, list[str]]:
    """Every chain hour of the split scanned for curve AND B2, and <= 5 % of tradeable coins missing B2 data."""
    notes = []
    if not cov.get("usable"):
        return False, ["no usable coins: the backfill has not reached this split yet"]
    if cov.get("chain_hours_scanned_frac", 0) < 0.999:
        notes.append(f"only {cov.get('chain_hours_scanned_frac', 0):.1%} of chain hours scanned")
    for d in cov.get("days", []):
        if d["curve_hours"] < d["hours_in_split"] or d["b2_hours"] < d["hours_in_split"]:
            notes.append(f"{d['day']}: curve {d['curve_hours']}/{d['hours_in_split']} h, "
                         f"B2 {d['b2_hours']}/{d['hours_in_split']} h")
    ex = cov.get("excluded") or {}
    miss = int(ex.get("b2_window_incomplete", 0)) + int(ex.get("no_b2_row", 0))
    trad = int(cov.get("tradeable") or 0)
    if trad and miss / trad > 0.05:
        notes.append(f"{miss}/{trad} tradeable coins lack a complete B2 window")
    return not notes, notes


def _ledger_runs(ledger_path: Path | None) -> list[dict]:
    with C._ledger(ledger_path, write=False) as led:
        return list(led.get("runs", []))


def _shortlist(h: str, shortlist_path: Path | None) -> dict | None:
    return _read_json(Path(shortlist_path or C.shortlist_dir()) / f"{h}.json")


def stage_variants(stage: str, out_dir: Path, shortlist_path: Path | None = None) -> list[str]:
    if stage in ("train", "debug"):
        return list(VARIANTS)
    if stage == "val":
        sl = _shortlist(HYP, shortlist_path)
        return [c["gate"] for c in sl["configs"]] if sl else []
    val = _read_json(out_dir / "val.json") or {}
    ship = (val.get("decision") or {}).get("ship")
    return [ship] if ship else []


def check_prereqs(stage: str, out_dir: Path = OUT_DIR, *, flow: Path | None = None,
                  ledger_path: Path | None = None, shortlist_path: Path | None = None,
                  env: Mapping[str, str] | None = None) -> dict:
    """Raise :class:`G1Refused` when ``stage`` may not run. Read-only (writes nothing)."""
    env = os.environ if env is None else env
    if stage not in STAGES + ("debug",):
        raise G1Refused(f"unknown stage {stage!r}")
    prereg = out_dir / "PREREG.md"
    if not prereg.exists():
        raise G1Refused(f"{prereg} missing: pre-register before any run")
    lock = _read_json(out_dir / "prereg.lock")
    if lock and lock.get("sha256") != _sha(prereg):
        raise G1Refused("PREREG.md changed after the first TRAIN run; record changes in G1/AMENDMENTS.md instead")
    ok, bad = data_gates(flow)
    if not ok:
        raise G1Refused("PLAN 8 rule 1 (data first): " + "; ".join(bad))
    info = {"stage": stage, "prereg_sha256": _sha(prereg), "prereg_locked": bool(lock)}
    if stage in ("debug", "train"):
        return info
    runs = _ledger_runs(ledger_path)
    split = STAGE_SPLIT[stage]
    if stage == "val":
        tr = _read_json(out_dir / "train.json")
        if not tr:
            raise G1Refused("no TRAIN result (G1/train.json): run --stage train first")
        if tr.get("provisional"):
            raise G1Refused("TRAIN ran on partial data (provisional): re-run --stage train on complete TRAIN data")
        for h, params in ((HYP, None), (HYP_DIP, DIP_PARAMS), (HYP_R0, R0_PARAMS)):
            sl = _shortlist(h, shortlist_path)
            if not sl:
                raise G1Refused(f"no VAL shortlist for {h}: it is written by a complete --stage train")
            if params is not None and C.params_hash(params) not in sl.get("hashes", []):
                raise G1Refused(f"{h} params are not in its VAL shortlist")
        if (out_dir / "val.json").exists():
            raise G1Refused("VAL already ran (G1/val.json exists): VAL is evaluated once")
        return info
    # one-run stages
    if stage == "test":
        val = _read_json(out_dir / "val.json")
        if not val:
            raise G1Refused("no VAL result (G1/val.json): TEST needs a VAL decision first")
        dec = val.get("decision") or {}
        if dec.get("verdict") not in SHIP_VERDICTS:
            raise G1Refused(f"VAL verdict {dec.get('verdict')}: G1 is stopped (PLAN 4.2 / 8); TEST is not spent")
    if stage in ("confirm", "final") and not (out_dir / "test.json").exists():
        raise G1Refused(f"never {stage.upper()} before TEST: run --stage test first")
    if (out_dir / f"{stage}.json").exists():
        raise G1Refused(f"{stage.upper()} already ran (G1/{stage}.json exists): one run per hypothesis")
    for h in (HYP, HYP_DIP, HYP_R0):
        if any(r.get("hypothesis") == h and r.get("split") == split and not r.get("debug") for r in runs):
            raise G1Refused(f"{h} already had its one {split} run (trials ledger)")
    if env.get(STAGE_ENV[stage]) != "1":
        raise G1Refused(f"{stage.upper()} is locked: set {STAGE_ENV[stage]}=1 (the judge's flag)")
    if not stage_variants(stage, out_dir, shortlist_path):
        raise G1Refused("no shipped variant in G1/val.json")
    return info


# =========================================================================== stage runner


def _jsonable(o: Any) -> Any:
    if isinstance(o, dict):
        return {str(k): _jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_jsonable(v) for v in o]
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (float, np.floating)):
        x = float(o)
        return None if math.isnan(x) or math.isinf(x) else x
    if o is pd.NA:
        return None
    return o


def _days(ds: C.Dataset, complete: bool) -> float:
    """Days of coin creation the run covers: the split bounds when complete, else the usable coins' span."""
    if complete and ds.split in C.SPLIT_BOUNDS:
        lo, hi = C.SPLIT_BOUNDS[ds.split]
        return (hi - lo) / 86400.0
    c = ds.coins["created_for_split"] if len(ds) else pd.Series(dtype=float)
    return max((float(c.max()) - float(c.min())) / 86400.0, 1e-9) if len(c) else float("nan")


def _coverage_counts(split: str, flow: Path | None, census: C.Census | None) -> dict:
    """Counts-only coverage of one split (no prices, no returns), like common.coverage_summary."""
    f = flow or C.flow_dir()
    g, c, b = (C._read_parquet(f / n) for n in ("graduates.parquet", "b2_coins.parquet", "b2_bars.parquet"))
    census = census if census is not None else C.Census.load()
    return C.Dataset.from_frames(split, g, c, b, census=census, guard=False).coverage


def run_stage(stage: str, *, out_dir: Path = OUT_DIR, allow_partial: bool = False, ds: C.Dataset | None = None,
              frames: tuple | None = None, census: C.Census | None = None, flow: Path | None = None,
              ledger_path: Path | None = None, shortlist_path: Path | None = None, B: int = 10_000,
              n_placebo: int = 20, env: Mapping[str, str] | None = None, _skip_coverage: bool = False) -> dict:
    """Run one stage end to end; writes G1/<stage>.json and .md. ``ds``/``frames`` injection is for tests."""
    t0 = time.time()
    out_dir = Path(out_dir)
    debug = stage == "debug"
    split = STAGE_SPLIT[stage]
    info = check_prereqs(stage, out_dir, flow=flow, ledger_path=ledger_path, shortlist_path=shortlist_path, env=env)
    if debug and ledger_path is None:
        ledger_path = C._SCRATCH / "lab2_debug" / "g1_debug_trials.json"   # keep debug means out of the real ledger
    variants = stage_variants(stage, out_dir, shortlist_path)
    cov = ds.coverage if ds is not None else _coverage_counts(split, flow, census)
    cov_ok, cov_notes = coverage_check(cov)
    provisional = False
    if not cov_ok and not (debug or _skip_coverage):
        if stage == "train" and allow_partial and cov.get("usable"):
            provisional = True
        else:
            raise G1Refused(f"{split} data incomplete: " + "; ".join(cov_notes[:6])
                            + (" (TRAIN only: --allow-partial for a provisional run)" if stage == "train" else ""))
    # commit to the run: ledger guards for every (hypothesis, config) BEFORE any data is read
    gate_cfgs = [{"gate": v} for v in variants]
    if not debug:
        try:
            for h, _fn, p in HOSTS.values():
                C._check_run_allowed(h, p, split, ledger_path, shortlist_path)
            for g in gate_cfgs:
                C._check_run_allowed(HYP, g, split, ledger_path, shortlist_path)
        except C.SplitLocked as e:
            raise G1Refused(str(e)) from e
    if stage == "train" and not (out_dir / "prereg.lock").exists():
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "prereg.lock").write_text(json.dumps({"sha256": info["prereg_sha256"],
                                                         "locked_utc": C.utc_str(time.time())}, indent=1))
    if ds is None:
        ds = C.load(split, flow=flow, census=census, _internal=(split == "val"))
    reg = registry_for(ds, frames=frames, census=census, flow=flow)
    coins_df = coin_table(ds, reg, labels=True)
    hide = debug
    res = {}
    for key, (h, fn, p) in HOSTS.items():
        res[key] = C.backtest(fn, split, p, hypothesis=h, ds=ds, placebo=(key == "dip"), n_placebo=n_placebo,
                              placebo_eligible=dip_universe_ok if key == "dip" else None, stress=STRESS,
                              declarations=DECL_HOST, ledger_path=ledger_path, shortlist_path=shortlist_path)
    trades = {k: annotate(r.trades, ds, reg) for k, r in res.items()}
    n_tr = C.n_trials(ledger_path)
    ev = eval_variants(variants, coins_df, trades, B=B, hide=hide, n_trials_total=n_tr)
    # one ledger trial per gate config (the gated R0 is its summary); debug runs never count
    gate_runs = {}
    for g in gate_cfgs:
        u = ev[g["gate"]]["hosts"].get("R0", {}).get("unflagged", {})
        gate_runs[g["gate"]] = C.record_run(HYP, g, split, {"n": u.get("n"), "mean": u.get("mean")},
                                            ledger_path, debug=debug)
    n_tr = C.n_trials(ledger_path)
    doc: dict[str, Any] = {
        "stage": stage, "split": split, "utc": C.utc_str(time.time()), "runtime_s": None, "provisional": provisional,
        "debug_only": debug, "prereg_sha256": info["prereg_sha256"], "g1_py_sha256": _sha(Path(__file__)),
        "data_files": ds.coverage.get("data_files"),
        "coverage": {k: ds.coverage.get(k) for k in ("bounds_utc", "graduates_in_split", "tradeable", "usable",
                                                      "excluded", "created_inexact", "has_create0",
                                                      "chain_hours_scanned_frac", "days_full", "days_expected",
                                                      "notes")},
        "coverage_ok": cov_ok, "coverage_notes": cov_notes,
        "variants": variants, "hosts_params": {k: v[2] for k, v in HOSTS.items()},
        "trials": {"n_trials_total": n_tr, "gate_runs": gate_runs,
                   "host_runs": {k: {kk: r.meta.get(kk) for kk in ("config", "new_trial", "hypothesis_configs",
                                                                     "over_variant_limit")}
                                 for k, r in res.items()}},
    }
    days = _days(ds, cov_ok)
    doc["counts"] = {
        "usable_coins": int(len(ds)), "split_days": days,
        "classes_at_g140": coins_df["g1_class"].value_counts().to_dict() if len(coins_df) else {},
        "flags_at_g140": {v: int(coins_df[f"flag_{v}"].sum()) for v in VARIANTS} if len(coins_df) else {},
        "unresolved_inputs": {"creator_unknown": int((~coins_df["creator_known"].astype(bool)).sum()),
                              "grad_delay_null": int(coins_df["grad_delay_s"].isna().sum())} if len(coins_df) else {},
        "serial_at_g140": int(coins_df["serial_flag"].sum()) if len(coins_df) else 0,
        "airdrop_by_window_end": int(coins_df["airdrop_by_end"].sum()) if len(coins_df) else 0,
        "registry": {"coins": reg.n_coins, "creators": len(reg.creator_ev), "wallets": len(reg.wallet_ev),
                     "warm_share_at_g140": float((coins_df["registry_cov"] >= REGISTRY_WARM_MIN).mean())
                     if len(coins_df) else None},
        "host_trades": {k: int(len(t)) for k, t in trades.items()},
        "host_trades_per_day": {k: (len(t) / days if days and days == days else None) for k, t in trades.items()},
        "host_trades_per_100_coins": {k: (100.0 * len(t) / len(ds) if len(ds) else None) for k, t in trades.items()},
        "host_trades_by_class": {k: (t["g1_class"].value_counts().to_dict() if len(t) else {}) for k, t in trades.items()},
        "host_trades_flagged": {k: {v: int(t[f"flag_{v}"].sum()) if len(t) else 0 for v in VARIANTS}
                                for k, t in trades.items()},
    }
    doc["hosts"] = {k: host_report(r, B, hide, n_tr) for k, r in res.items()}
    doc["classes"] = class_tables(coins_df, trades, B=min(B, 2000), hide=hide)
    doc["variants_eval"] = ev
    if stage == "train":
        sl = shortlist_rule(ev)
        doc["decision"] = {"shortlist": sl, "rule": "G-time + the chain variant whose kept R0 trades have the "
                           "higher mean (tie -> G-chain)"}
        if not provisional:
            try:
                C.write_shortlist(HYP, sl, path=shortlist_path, ledger_path=ledger_path, note="G1 PREREG rule")
                C.write_shortlist(HYP_DIP, [DIP_PARAMS], path=shortlist_path, ledger_path=ledger_path,
                                  note="fixed host")
                C.write_shortlist(HYP_R0, [R0_PARAMS], path=shortlist_path, ledger_path=ledger_path, note="fixed host")
                doc["decision"]["shortlist_written"] = True
            except C.SplitLocked as e:
                doc["decision"]["shortlist_written"] = False
                doc["decision"]["shortlist_note"] = str(e)
        else:
            doc["decision"]["shortlist_written"] = False
            doc["decision"]["shortlist_note"] = "provisional (partial TRAIN data): no shortlist"
    elif stage == "val":
        sl = _shortlist(HYP, shortlist_path)
        doc["decision"] = decide_val(ev, sl["configs"])
    elif stage in ("test", "confirm", "final"):
        doc["decision"] = decide_confirm(ev, variants[0])
        if stage == "final" and len(trades["R0"]):
            thirds = {}
            for third in C.FINAL_SPLITS:
                sub = trades["R0"][trades["R0"]["split"] == third]
                fl = sub[f"flag_{variants[0]}"].to_numpy(bool) if len(sub) else np.zeros(0, bool)
                thirds[third] = {"flagged": _cell(sub[fl], 2000, False), "unflagged": _cell(sub[~fl], 2000, False)}
            doc["decision"]["by_third_R0"] = thirds
    else:
        doc["decision"] = {"debug": "counts only; returns, dead60 / winner rates and decisions are hidden"}
    doc["runtime_s"] = round(time.time() - t0, 1)
    doc = _jsonable(doc)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{stage}.json").write_text(json.dumps(doc, indent=1, sort_keys=False))
    (out_dir / f"{stage}.md").write_text(render_md(doc))
    if not debug:
        keep = [c for c in next(iter(trades.values())).columns
                if not any(c in (f"flag_{v}", f"dead_{v}") for v in VARIANTS if v not in variants)]
        allt = pd.concat([t.assign(host=k) for k, t in trades.items()], ignore_index=True)
        allt[[c for c in keep if c in allt] + ["host"]].to_csv(out_dir / f"{stage}_trades.csv.gz", index=False)
    return doc


# =========================================================================== report


def _pct(x, nd=1):
    return "n/a" if x is None else f"{100 * x:+.{nd}f}%"


def _rate(x):
    return "n/a" if x is None else f"{100 * x:.1f}%"


def _ci(ci):
    return "n/a" if not ci else f"[{100 * ci[0]:+.1f}, {100 * ci[1]:+.1f}]"


def render_md(doc: Mapping[str, Any]) -> str:
    L = [f"# G1 {doc['stage']} ({doc['split']})", ""]
    L.append(f"Run {doc['utc']} UTC, {doc.get('runtime_s')} s. PREREG sha256 `{doc['prereg_sha256'][:12]}`. "
             f"Trials in the ledger: {doc['trials']['n_trials_total']}.")
    if doc.get("provisional"):
        L.append("**PROVISIONAL: partial TRAIN data, no shortlist written.**")
    if doc.get("debug_only"):
        L.append("**DEBUG (census TRAIN third): counts only. Returns, label rates and decisions are hidden.**")
    cnt = doc["counts"]
    L += ["", "## Counts", "",
          f"- Usable coins: {cnt['usable_coins']} over {cnt['split_days']:.2f} days of creation.",
          f"- Classes at g + 140 s: {cnt['classes_at_g140']}.",
          f"- Flagged at g + 140 s: {cnt['flags_at_g140']}. SERIAL: {cnt['serial_at_g140']}. "
          f"Airdrop dump by the window end: {cnt['airdrop_by_window_end']}.",
          f"- Host trades: {cnt['host_trades']} (per day {_fmt_map(cnt['host_trades_per_day'])}; per 100 coins "
          f"{_fmt_map(cnt['host_trades_per_100_coins'])}).",
          f"- Host trades by class: {cnt['host_trades_by_class']}.",
          f"- Registry: {cnt['registry']}."]
    if doc.get("coverage_notes"):
        L.append(f"- Coverage notes: {'; '.join(doc['coverage_notes'][:4])}.")
    if not doc.get("debug_only"):
        L += ["", "## Hosts (ungated)", "", "| Host | n | coins | mean | 95% CI | placebo diff | costs x1.5 | alt fill |",
              "|---|---:|---:|---:|---|---:|---:|---:|"]
        for k, h in doc["hosts"].items():
            s = h.get("summary") or {}
            pl = (h.get("placebo") or {}).get("mean_diff")
            st = h.get("stress") or {}
            L.append(f"| {k} | {h['n']} | {h['n_coins']} | {_pct(s.get('mean'))} | {_ci(s.get('ci95'))} | "
                     f"{_pct(pl)} | {_pct((st.get('costs_x1.5') or {}).get('mean'))} | "
                     f"{_pct((st.get('alt_fill') or {}).get('mean'))} |")
        L += ["", "## How much each class loses (host trades classified at their decision time)", "",
              "| Host | Class | n | mean | 95% CI | P&L $ |", "|---|---|---:|---:|---|---:|"]
        for hk, tab in doc["classes"]["hosts"].items():
            for cls, c in tab.items():
                if cls.startswith("_") or cls.startswith("noflag:") or not isinstance(c, dict) or not c.get("n"):
                    continue
                L.append(f"| {hk} | {cls} | {c['n']} | {_pct(c.get('mean'))} | {_ci(c.get('ci95'))} | "
                         f"{c.get('pnl_usd', 0):+.0f} |")
        L += ["", "## Gate variants", "", "| Variant | flagged coins (dead set) | precision dead60 | missed winners | "
              "R0 flagged - unflagged [95% CI] | R0 kept mean | dip flagged - unflagged |", "|---|---:|---:|---:|---|---:|---:|"]
        for v in doc["variants"]:
            e = doc["variants_eval"][v]
            lab, r0, dp = e["labels"], e["hosts"].get("R0", {}), e["hosts"].get("dip", {})
            L.append(f"| {v} | {lab.get('n_flag_dead')} | {_rate(lab.get('precision_dead60'))} | "
                     f"{_rate(lab.get('missed_winner_rate'))} | {_pct(r0.get('diff_flagged_minus_unflagged'))} "
                     f"{_ci(r0.get('diff_ci95'))} | {_pct((r0.get('unflagged') or {}).get('mean'))} | "
                     f"{_pct(dp.get('diff_flagged_minus_unflagged'))} (n {dp.get('flagged', {}).get('n')}/"
                     f"{dp.get('unflagged', {}).get('n')}) |")
        cmp = doc["variants_eval"].get("_chain_vs_time_R0") or {}
        for v, c in cmp.items():
            L.append(f"- {v} vs G-time on R0's kept trades: {_pct(c.get('r0_unflagged_mean_minus_g_time'))} "
                     f"{_ci(c.get('ci95'))}.")
    L += ["", "## Decision", "", "```", json.dumps(doc.get("decision"), indent=1)[:3000], "```", ""]
    return "\n".join(L)


def _fmt_map(m: Mapping[str, Any]) -> str:
    return ", ".join(f"{k} {v:.1f}" if isinstance(v, (int, float)) and v is not None else f"{k} n/a"
                     for k, v in m.items())


# =========================================================================== CLI


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="G1 gate (PLAN 4.2): pre-registered stages; see G1/PREREG.md")
    ap.add_argument("--stage", choices=STAGES)
    ap.add_argument("--debug", action="store_true", help="census TRAIN third, counts only (returns hidden)")
    ap.add_argument("--allow-partial", action="store_true", help="TRAIN only: provisional run on partial data")
    ap.add_argument("--check", action="store_true", help="check the stage's prerequisites and exit")
    ap.add_argument("--bootstrap", type=int, default=10_000)
    a = ap.parse_args(argv)
    stage = "debug" if a.debug else a.stage
    if stage is None:
        ap.error("--stage or --debug is required")
    try:
        if a.check:
            info = check_prereqs(stage)
            cov_ok, notes = coverage_check(_coverage_counts(STAGE_SPLIT[stage], None, None))
            print(json.dumps({"prerequisites": "ok", **info, "coverage_ok": cov_ok, "coverage_notes": notes[:8]},
                             indent=1))
            return 0
        doc = run_stage(stage, allow_partial=a.allow_partial, B=a.bootstrap)
    except G1Refused as e:
        print(f"REFUSED ({stage}): {e}", file=sys.stderr)
        return 2
    print(f"G1 {stage}: wrote {OUT_DIR / (stage + '.json')} and .md in {doc['runtime_s']} s")
    print(json.dumps({"counts": doc["counts"], "decision": doc.get("decision")}, indent=1, default=str)[:4000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
