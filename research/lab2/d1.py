"""D1 (PLAN §4.4): buy dips caused by capitulation, not by insiders distributing.

Research only (wave-2 lab); nothing here is wired into the bot. Pre-registration: ``research/lab2/D1/PREREG.md``
(frozen at the first TRAIN run by ``D1/prereg.lock``).

Mechanism. Two kinds of dip look identical on candles. In a DISTRIBUTION dip, insiders who hold inventory bought
10x below the price keep selling, and the dip continues. In a CAPITULATION dip, many late organic holders sell at a
loss and empty their positions; that selling runs out quickly. D1 buys only the second kind.

THE ONE RULE OF THIS FILE: every feature comes through ``common.AsOf`` (cutoff tau = t - 20 s): bars through
``snap.bars`` / ``snap.price`` / ``snap.max_high`` / ``snap.vol_usd``, static fields through ``snap[...]`` at their
legal time, raw B1 trades through ``snap.trades`` (rows with ts <= tau). Nothing reads a Dataset / CoinData column,
so the common.py lookahead rules (and their tests) cover D1 as well.

Why B1 is mandatory. The PLAN's classes are wallet-level: the cost basis of what is sold (``sopr3``), who sells
(insiders vs organic), how much insider inventory is left, how many organic wallets buy. Minute bars carry no
wallet roles, so there is no bar-only D1: a coin without B1 rows is SKIPPED, and a stage refuses to run when B1
covers < 95 % of the split's eligible coins (``--allow-partial`` runs TRAIN as a preview without a shortlist).

CLI (every stage writes ``D1/<stage>.json`` + ``D1/<stage>.md`` and exits with code 2 when a prerequisite is
missing)::

    python research/lab2/d1.py --stage status                    # coverage, prerequisites, trials (no returns)
    python research/lab2/d1.py --stage debug                     # census TRAIN third: counts only
    python research/lab2/d1.py --stage train [--allow-partial]
    python research/lab2/d1.py --stage val
    LAB2_ALLOW_TEST=1    python research/lab2/d1.py --stage test
    LAB2_ALLOW_CONFIRM=1 python research/lab2/d1.py --stage confirm
    LAB2_ALLOW_FINAL=1   python research/lab2/d1.py --stage final
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import math
import os
import struct
import sys
import tempfile
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import common as C  # noqa: E402

VERSION = "d1-v1"
HYP, HYP_EVENT = "D1", "D1-event"


def d1_dir() -> Path:
    return Path(os.environ.get("LAB2_D1_DIR", str(HERE / "D1")))


# =========================================================================== pre-registered constants (PREREG §3-§6)

SUPPLY = 1e9                     # whole tokens
TOK = 1e6                        # raw token units per whole token
LAMPORTS = 1e9

# E1, the candle dip (PLAN 4.4), evaluated at the minute close tau (decision t = tau + 20 s)
E1_DD15 = 0.25                   # dd15 = 1 - close / max(high over (tau - 15 min, tau]) >= 0.25
E1_DD_WINDOW_S = 900
E1_FLOOR_MULT = 3.0              # close >= 3 x p_floor, p_floor = k / (1e9 - burned)^2
E1_MIN_AGE_S = 600               # age at the minute close (tau - g) >= 10 min
E1_VOL_USD_15M = 1500.0          # USD volume over the last 15 completed minutes

# decision window: B1 covers [created, g + 120 min); entries only while the prefix is complete
B1_HORIZON_S = 7200
MAX_DECISION_AGE_S = 7200        # t - g <= 7200  ->  tau <= g + 7180
B1_MAX_TRADES = 20000            # P4 keeps the first 20,000 trades per coin: a prefix this long may be truncated
B1_MIN_COVERAGE = 0.95

# seller window and classes (PLAN 4.4)
WIN3_S = 180
FULL_EXIT_FRAC = 0.01            # a sell that leaves pos <= 1 % of the seller's peak is a full exit
ORPHAN_TOL = 0.02                # orphan part counts only above 2 % of the sell (B1 drops dust buys)
CAP_DEFS: dict[str, dict[str, float]] = {
    "strict": {"sopr_max": 0.8, "ins_share_max": 0.2, "n_sellers_min": 8, "insider_rem_max": 0.15,
               "org_buyers_min": 5},
    "loose": {"sopr_max": 1.0, "ins_share_max": 0.2, "n_sellers_min": 5, "insider_rem_max": 0.15,
              "org_buyers_min": 5},
}
DIST_SOPR_MIN, DIST_INS_SHARE_MIN = 2.0, 0.5

# roles (PLAN 3.2)
SNIPER_WINDOW_S, SNIPER_FIRST_N = 60, 20
BOT_MIN_TRADES, BOT_MEDIAN_HOLD_S, BOT_RT_S, BOT_MIN_RT = 4, 10.0, 60.0, 3
WASH_S, WASH_REL = 60.0, 0.05
MECH_WINDOW_S, MECH_MIN_BUYS, MECH_MAX_SELL_FRAC = 1800, 6, 0.10
MECH_GAP_CV, MECH_SIZE_CV, MECH_SPEARMAN, MECH_RET_S = 0.25, 0.5, 0.3, 60

# G1 gate, on-chain classes (PLAN 4.2 "G-chain"); NEWS needs IPFS metadata: not computed (merged into ORGANIC)
G1_INSTANT_MAX_DELAY_S = 5.0
G1_OPERATOR_MIN_BUY_SOL, G1_OPERATOR_MAX_BUYERS = 500.0, 30
G1_FACTORY_MIN_TOP5 = 0.85
G1_COMPLETED_SHARE, G1_COMPLETED_TOP3, G1_COMPLETED_MIN_BUYERS = 0.6, 0.6, 15
G1_COMPLETER_WINDOW_SOL = 30.0

# exits
BRACKET = C.ExitSpec(stop_pct=0.15, take_profit_pct=0.25, max_hold_s=1800)    # E1: +25 % / -15 % / 30 min
S1X_TRAIL, S1X_MAX_HOLD_S = 0.30, 5400                                         # S1 exit set (PLAN 4.3)
S1X_ORG_NET5_SOL, S1X_ORPHAN10, S1X_CREATOR_SOLD, S1X_INSIDER_GROWTH = -1.0, 0.25, 0.20, 0.02

# the TRAIN grid (every point is a trial)
VARIANTS = {"V1": ("strict", "bracket"), "V2": ("loose", "bracket"), "V3": ("strict", "s1")}
EVENT_CLASSES = ("CAP", "CAP_LOOSE", "DIST", "MIXED", "ALL")
HORIZONS_MIN = (15, 30, 60)
PRIMARY_HORIZON_MIN = 30

# selection and the VAL gate (stop rule 4)
SHORTLIST_MIN_TRADES, SHORTLIST_MIN_COINS = 30, 20
VAL_MIN_TRADES = 15
GATE_KILL_BELOW, GATE_PASS_AT, GATE_MIN_TRADES = 0.05, 0.10, 20
N_PLACEBO = 20
BOOT_B = 10_000

DECLARATIONS = {
    "uses_organic_flow": True, "organic_excludes": ["AGENT", "BOT", "WASH", "DUST", "MECH"],
    "uses_wallet_reputation": False, "uses_truncated_windows": False, "uses_current_state_fields": False,
    "notes": ["ORGANIC also excludes INSIDER (CREATOR, BUNDLE, SNIPER, COMPLETER, TRANSFEREE) and pooled accounts",
              "BOT is the in-coin rule only (no B3 registry)", "TRANSFEREE from orphan sells only (no B4 transfers)",
              "DUST is absent from B1 (trades < 0.01 SOL dropped at collection)",
              "minute-bar 'worst' fills until X1 exists"],
}


class StageRefused(RuntimeError):
    """A stage's prerequisites are missing (the CLI exits with code 2)."""


# =========================================================================== wallet hashing (ClickHouse cityHash64)

_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_B58_IDX = {ch: i for i, ch in enumerate(_B58)}
_M64 = (1 << 64) - 1
_K0, _K1, _K2, _K3 = 0xC3A5C85C97CB3127, 0xB492B66FBE98F273, 0x9AE16A3B2F90404F, 0xC949D7C7509E6557


def b58decode(s: str) -> bytes:
    n = 0
    for ch in s:
        n = n * 58 + _B58_IDX[ch]
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big") if n else b""
    return b"\x00" * (len(s) - len(s.lstrip("1"))) + raw


def b58encode(b: bytes) -> str:
    n = int.from_bytes(b, "big")
    out = ""
    while n:
        n, r = divmod(n, 58)
        out = _B58[r] + out
    return "1" * (len(b) - len(b.lstrip(b"\x00"))) + out


def _rot(v: int, s: int) -> int:
    return v if s == 0 else ((v >> s) | (v << (64 - s))) & _M64


def _hash_len16(u: int, v: int) -> int:
    kmul = 0x9DDFEA08EB382D69
    a = ((u ^ v) * kmul) & _M64
    a ^= a >> 47
    b = ((v ^ a) * kmul) & _M64
    b ^= b >> 47
    return (b * kmul) & _M64


def cityhash64(b: bytes) -> int:
    """ClickHouse ``cityHash64`` (CityHash v1.0.2, HashLen17to32) for 17-32 byte strings (Solana keys: 32)."""
    n = len(b)
    if not 17 <= n <= 32:
        raise ValueError("cityhash64 port covers 17-32 byte inputs only")
    f = lambda i: struct.unpack_from("<Q", b, i)[0]  # noqa: E731
    a = (f(0) * _K1) & _M64
    bb = f(8)
    c = (f(n - 8) * _K2) & _M64
    d = (f(n - 16) * _K0) & _M64
    return _hash_len16((_rot((a - bb) & _M64, 43) + _rot(c, 30) + d) & _M64,
                       (a + _rot(bb ^ _K3, 20) - c + n) & _M64)


def wallet_h(address: Any) -> int | None:
    """B1 ``wallet_h`` of a base58 address, or None when it is not a 32-byte base58 key."""
    if not isinstance(address, str) or not address:
        return None
    try:
        raw = b58decode(address)
    except KeyError:
        return None
    return cityhash64(raw) if len(raw) == 32 else None


_POOLED_H: frozenset[int] | None = None


def pooled_hashes() -> frozenset[int]:
    global _POOLED_H
    if _POOLED_H is None:
        addrs = set(C.POOLED_ACCOUNTS) | C._pooled_from_file()
        _POOLED_H = frozenset(h for h in (wallet_h(a) for a in addrs) if h is not None)
    return _POOLED_H


# =========================================================================== the wallet ledger (PLAN 3.2)

_TRADE_COLS = ("ts", "venue", "buy", "sol", "tok", "code", "slot", "pb", "pa", "peak", "basis", "orphan", "hold",
               "wash", "price", "pooled_t")


class _Ledger:
    """Wallet ledger of one coin's B1 trade prefix, replayed in chain order.

    Per trade: position before/after, running peak, average-cost basis of the tokens sold (orphan tokens cost 0),
    the effective orphan part, the hold since the wallet's last buy, a WASH flag (opposite side within 60 s with a
    size within 5 %) and the pool price before the trade. Every per-trade value depends only on EARLIER trades, so
    a ledger built on a longer prefix is valid for any shorter one (``arrays(n)``)."""

    def __init__(self, pooled: frozenset[int]) -> None:
        self.pooled = pooled
        self.n = 0
        self.code_of: dict[int, int] = {}
        self.wh: list[int] = []
        self.pooled_w: list[bool] = []
        self._pos: list[float] = []
        self._cost: list[float] = []
        self._peak: list[float] = []
        self._last_buy: list[float] = []
        self._last_side: list[int] = []
        self._last_ts: list[float] = []
        self._last_tok: list[float] = []
        self._cols: dict[str, list] = {k: [] for k in _TRADE_COLS}
        self.cs: np.ndarray = np.zeros(0)
        self._np: dict[str, np.ndarray] | None = None

    def extend(self, tr: pd.DataFrame, cs: np.ndarray) -> None:
        m = len(tr)
        if not m:
            return
        ts = tr["ts"].to_numpy(np.float64)
        venue = tr["venue"].to_numpy(np.int64)
        isb = tr["is_buy"].to_numpy().astype(bool)
        sol = tr["usol"].to_numpy(np.float64) / LAMPORTS
        tok = tr["tok"].to_numpy(np.float64) / TOK
        wh = tr["wallet_h"].to_numpy(np.uint64)
        slot = tr["slot"].to_numpy(np.int64)
        x0 = tr["x0"].to_numpy(np.float64)
        y0 = tr["y0"].to_numpy(np.float64)
        virt = tr["virt_ksol"].to_numpy(np.float64) * 1000.0 if "virt_ksol" in tr else np.zeros(m)
        pooled_col = tr["pooled"].to_numpy().astype(bool) if "pooled" in tr else np.zeros(m, bool)
        cols = self._cols
        for i in range(m):
            w = int(wh[i])
            c = self.code_of.get(w)
            if c is None:
                c = len(self.wh)
                self.code_of[w] = c
                self.wh.append(w)
                self.pooled_w.append(w in self.pooled)
                self._pos.append(0.0)
                self._cost.append(0.0)
                self._peak.append(0.0)
                self._last_buy.append(math.nan)
                self._last_side.append(-1)
                self._last_ts.append(math.nan)
                self._last_tok.append(0.0)
            if pooled_col[i]:
                self.pooled_w[c] = True
            b, s, q, t = bool(isb[i]), float(sol[i]), float(tok[i]), float(ts[i])
            pb = self._pos[c]
            if b:
                if pb < 0 and q > 0:
                    cov = min(q, -pb)
                    self._cost[c] += s * (q - cov) / q
                else:
                    self._cost[c] += s
                pa = pb + q
                basis = orphan = 0.0
                hold = math.nan
                self._last_buy[c] = t
            else:
                held = pb if pb > 0 else 0.0
                cov = q if q < held else held
                basis = self._cost[c] * cov / held if held > 0 else 0.0
                self._cost[c] -= basis
                raw = q - cov
                orphan = raw if raw > ORPHAN_TOL * q else 0.0
                pa = pb - q
                hold = t - self._last_buy[c]
            if pa > self._peak[c]:
                self._peak[c] = pa
            ls = self._last_side[c]
            lt = self._last_tok[c]
            wash = (ls >= 0 and ls != int(b) and t - self._last_ts[c] <= WASH_S
                    and abs(q - lt) < WASH_REL * max(q, lt))
            self._last_side[c], self._last_ts[c], self._last_tok[c] = int(b), t, q
            self._pos[c] = pa
            px = ((x0[i] + virt[i]) / LAMPORTS) / (y0[i] / TOK) if venue[i] == 1 and y0[i] > 0 else math.nan
            for k, v in (("ts", t), ("venue", int(venue[i])), ("buy", b), ("sol", s), ("tok", q), ("code", c),
                         ("slot", int(slot[i])), ("pb", pb), ("pa", pa), ("peak", self._peak[c]),
                         ("basis", basis), ("orphan", orphan), ("hold", hold), ("wash", bool(wash)), ("price", px),
                         ("pooled_t", bool(pooled_col[i]))):
                cols[k].append(v)
        self.n += m
        self.cs = np.concatenate([self.cs, cs]) if len(self.cs) else np.asarray(cs, np.float64)
        self._np = None

    def arrays(self, n: int) -> dict[str, np.ndarray]:
        if self._np is None:
            dt = {"ts": np.float64, "venue": np.int64, "buy": bool, "sol": np.float64, "tok": np.float64,
                  "code": np.int64, "slot": np.int64, "pb": np.float64, "pa": np.float64, "peak": np.float64,
                  "basis": np.float64, "orphan": np.float64, "hold": np.float64, "wash": bool,
                  "price": np.float64, "pooled_t": bool}
            self._np = {k: np.asarray(v, dtype=dt[k]) for k, v in self._cols.items()}
            self._np["wh"] = np.asarray(self.wh, dtype=np.uint64)
            self._np["pooled_w"] = np.asarray(self.pooled_w, dtype=bool)
        out = {k: v[:n] for k, v in self._np.items() if k not in ("wh", "pooled_w")}
        nw = int(out["code"].max()) + 1 if n else 0
        out["wh"] = self._np["wh"][:nw]
        pw = self._np["pooled_w"][:nw].copy()
        if n and out["pooled_t"].any():          # pooled flag carried by the trades themselves (load() adds it)
            pw[np.unique(out["code"][out["pooled_t"]])] = True
        out["pooled_w"] = pw
        out["nw"] = nw
        return out


class _LRU(OrderedDict):
    def __init__(self, cap: int) -> None:
        super().__init__()
        self.cap = cap

    def get(self, k, default=None):
        if k in self:
            self.move_to_end(k)
            return self[k]
        return default

    def put(self, k, v) -> None:
        self[k] = v
        self.move_to_end(k)
        while len(self) > self.cap:
            self.popitem(last=False)


_LEDGERS = _LRU(32)
_FEATS = _LRU(300_000)


def clear_cache() -> None:
    _LEDGERS.clear()
    _FEATS.clear()


def _checksums(tr: pd.DataFrame) -> np.ndarray:
    """Cumulative content checksum of a trade prefix (identifies 'the same first n rows')."""
    if not len(tr):
        return np.zeros(0)
    p = 1_000_003.0
    v = (np.mod(tr["slot"].to_numpy(np.float64), p) * 3.0
         + np.mod(tr["usol"].to_numpy(np.float64), p) * 5.0
         + np.mod(tr["tok"].to_numpy(np.float64), p) * 7.0
         + np.mod((tr["wallet_h"].to_numpy(np.uint64) % np.uint64(1_000_037)).astype(np.float64), p) * 11.0
         + np.mod(tr["ts"].to_numpy(np.float64), p) * 13.0
         + tr["is_buy"].to_numpy().astype(np.float64) * 17.0)
    if "tx_idx" in tr:
        v = v + np.mod(tr["tx_idx"].to_numpy(np.float64), p) * 19.0
    return np.cumsum(v + 1.0)


def _ledger_for(mint: str, tr: pd.DataFrame) -> tuple[_Ledger, int, float]:
    """Ledger valid for exactly the rows of ``tr`` (built, extended or re-used by content)."""
    n = len(tr)
    cs = _checksums(tr)
    last = float(cs[-1]) if n else 0.0
    L = _LEDGERS.get(mint)
    if L is not None:
        if L.n >= n and (n == 0 or L.cs[n - 1] == cs[n - 1]):
            return L, n, last
        if L.n < n and (L.n == 0 or L.cs[L.n - 1] == cs[L.n - 1]):
            L.extend(tr.iloc[L.n:n], cs[L.n:n])
            return L, n, last
    L = _Ledger(pooled_hashes())
    L.extend(tr, cs)
    _LEDGERS.put(mint, L)
    return L, n, last


# =========================================================================== roles and seller features (as of tau)


@dataclass(frozen=True)
class Static:
    """Per-coin facts read through AsOf at their legal time (hashed wallets; None = unknown)."""

    g: float
    created: float | None
    c_slot: int | None
    creator_h: int | None
    completer_h: int | None
    agent_h: int | None


def static_of(snap: C.AsOf) -> Static:
    agent = snap.get("agent_wallet") if snap.agent_detected else None
    created = snap.get("created_ts")
    cs = snap.get("c_slot")
    return Static(g=float(snap.g), created=None if created is None else float(created),
                  c_slot=None if cs is None else int(cs), creator_h=wallet_h(snap.get("creator")),
                  completer_h=wallet_h(snap.get("completer30")), agent_h=wallet_h(agent))


def _code(L: _Ledger, h: int | None, nw: int) -> int:
    if h is None:
        return -1
    c = L.code_of.get(h, -1)
    return c if c < nw else -1


def _bot_mask(A: dict, nw: int) -> np.ndarray:
    code, buy, hold = A["code"], A["buy"], A["hold"]
    ntr = np.bincount(code, minlength=nw)
    cand = ntr >= BOT_MIN_TRADES
    bot = np.zeros(nw, bool)
    sel = (~buy) & np.isfinite(hold) & cand[code]
    if not sel.any():
        return bot
    cs, hs = code[sel], hold[sel]
    rt = np.bincount(cs[hs <= BOT_RT_S], minlength=nw)
    o = np.lexsort((hs, cs))
    co, ho = cs[o], hs[o]
    u, start, cnt = np.unique(co, return_index=True, return_counts=True)
    med = (ho[start + (cnt - 1) // 2] + ho[start + cnt // 2]) / 2.0
    bot[u[med < BOT_MEDIAN_HOLD_S]] = True
    bot |= (rt >= BOT_MIN_RT) & cand
    return bot


def _spearman(a: np.ndarray, b: np.ndarray) -> float:
    if len(a) < 3:
        return math.nan
    ra = pd.Series(a).rank().to_numpy(float)
    rb = pd.Series(b).rank().to_numpy(float)
    if ra.std() == 0 or rb.std() == 0:
        return math.nan
    return float(np.corrcoef(ra, rb)[0, 1])


def _mech_mask(A: dict, nw: int, tau: float, exclude: Iterable[int]) -> np.ndarray:
    """MECH (PLAN 4.5) over pool trades in (tau - 30 min, tau]; AGENT and CREATOR never count."""
    code, ts, buy, venue, sol, price = A["code"], A["ts"], A["buy"], A["venue"], A["sol"], A["price"]
    mech = np.zeros(nw, bool)
    win = (ts > tau - MECH_WINDOW_S) & (venue == 1)
    wb = win & buy
    if wb.sum() < MECH_MIN_BUYS:
        return mech
    cnt = np.bincount(code[wb], minlength=nw)
    cand = set(np.nonzero(cnt >= MECH_MIN_BUYS)[0].tolist()) - {c for c in exclude if c >= 0}
    if not cand:
        return mech
    pidx = np.nonzero(venue == 1)[0]
    pts, ppx = ts[pidx], price[pidx]
    for c in sorted(cand):
        bi = np.nonzero(wb & (code == c))[0]
        bsol = float(sol[bi].sum())
        ssol = float(sol[win & ~buy & (code == c)].sum())
        if ssol > MECH_MAX_SELL_FRAC * bsol:
            continue
        gaps = np.diff(ts[bi])
        if len(gaps) < 2 or gaps.mean() <= 0 or gaps.std() / gaps.mean() >= MECH_GAP_CV:
            continue
        sizes = sol[bi]
        if sizes.mean() <= 0 or sizes.std() / sizes.mean() >= MECH_SIZE_CV:
            continue
        j = np.searchsorted(pts, ts[bi] - MECH_RET_S, side="right")
        j = np.minimum(j, len(pts) - 1)
        ret = price[bi] / ppx[j] - 1.0
        rho = _spearman(sizes, ret)
        if not (abs(rho) >= MECH_SPEARMAN):        # NaN (constant series) counts as price-ignoring
            mech[c] = True
    return mech


def roles_at(L: _Ledger, A: dict, st: Static, tau: float) -> dict[str, Any]:
    """Role masks over wallet codes as of tau (the prefix A holds only trades with ts <= tau)."""
    nw = A["nw"]
    code, ts, venue, buy, slot = A["code"], A["ts"], A["venue"], A["buy"], A["slot"]
    pooled = A["pooled_w"]
    ins = np.zeros(nw, bool)
    creator_c, completer_c, agent_c = (_code(L, h, nw) for h in (st.creator_h, st.completer_h, st.agent_h))
    if creator_c >= 0:
        ins[creator_c] = True
    cb = (venue == 0) & buy
    bundle = np.zeros(nw, bool)
    if st.c_slot is not None:
        bundle[np.unique(code[cb & (slot == st.c_slot)])] = True
    sniper = np.zeros(nw, bool)
    if cb.any():
        u, first = np.unique(code[cb], return_index=True)
        order = np.argsort(first, kind="stable")
        sniper[u[order[:SNIPER_FIRST_N]]] = True
        if st.created is not None:
            sniper[u[ts[cb][first] <= st.created + SNIPER_WINDOW_S]] = True
    completer = np.zeros(nw, bool)
    if completer_c >= 0:
        completer[completer_c] = True
    transferee = np.zeros(nw, bool)
    transferee[np.unique(code[A["orphan"] > 0])] = True
    ins |= bundle | sniper | completer | transferee
    ins &= ~pooled
    agent = np.zeros(nw, bool)
    if agent_c >= 0:
        agent[agent_c] = True
    bot = _bot_mask(A, nw)
    wash = np.zeros(nw, bool)
    wash[np.unique(code[A["wash"]])] = True
    mech = _mech_mask(A, nw, tau, (agent_c, creator_c))
    org = ~(ins | agent | bot | wash | mech | pooled)
    return {"ins": ins, "agent": agent, "bot": bot, "wash": wash, "mech": mech, "org": org, "pooled": pooled,
            "creator_c": creator_c, "completer_c": completer_c, "agent_c": agent_c,
            "counts": {"insiders": int(ins.sum()), "bundle": int(bundle.sum()), "snipers": int(sniper.sum()),
                       "transferees": int((transferee & ~pooled).sum()), "bots": int(bot.sum()),
                       "wash": int(wash.sum()), "mech": int(mech.sum()), "organic": int(org.sum())}}


def _features_from(L: _Ledger, A: dict, st: Static, tau: float, tau_entry: float | None) -> dict[str, Any]:
    R = roles_at(L, A, st, tau)
    code, ts, buy, sol, tok = A["code"], A["ts"], A["buy"], A["sol"], A["tok"]
    n = len(code)
    pooled_t = R["pooled"][code] if n else np.zeros(0, bool)
    ins_t = R["ins"][code] if n else np.zeros(0, bool)
    org_t = R["org"][code] if n else np.zeros(0, bool)
    w3 = ts > tau - WIN3_S
    s3 = w3 & ~buy & ~pooled_t
    S_all = float(sol[s3].sum())
    S_ins = float(sol[s3 & ins_t].sum())
    basis3 = float(A["basis"][s3].sum())
    if S_all > 0:
        sopr3 = S_all / basis3 if basis3 > 0 else math.inf
        ins_share3 = S_ins / S_all
        full3 = float(sol[s3 & (A["pa"] <= FULL_EXIT_FRAC * A["peak"])].sum()) / S_all
    else:
        sopr3 = ins_share3 = full3 = None
    d = np.where(ins_t, np.maximum(A["pa"], 0.0) - np.maximum(A["pb"], 0.0), 0.0)
    run = np.cumsum(d)
    H = float(run[-1]) if n else 0.0
    Hpk = float(max(run.max(), 0.0)) if n else 0.0
    f: dict[str, Any] = {
        "ok": True, "why": "", "n_trades": int(n),
        "sopr3": sopr3, "ins_sell_share3": ins_share3, "n_sellers3": int(len(np.unique(code[s3]))),
        "full_exit_share3": full3, "sell_sol3": S_all, "insider_sell_sol3": S_ins,
        "insider_rem": H / Hpk if Hpk > 0 else None, "insider_hold_tok": H, "insider_peak_tok": Hpk,
        "org_buyers3": int(len(np.unique(code[w3 & buy & org_t]))),
        "agent_tok": float(tok[buy & (code == R["agent_c"])].sum()) if R["agent_c"] >= 0 else 0.0,
        **{f"n_{k}": v for k, v in R["counts"].items()},
    }
    if tau_entry is not None:
        w5 = ts > tau - 300
        f["org_net5"] = float(sol[w5 & buy & org_t].sum() - sol[w5 & ~buy & org_t].sum())
        s10 = (ts > tau - 600) & ~buy & ~pooled_t
        t10 = float(tok[s10].sum())
        f["orphan_share10"] = float(A["orphan"][s10].sum()) / t10 if t10 > 0 else None
        cc = R["creator_c"]
        if cc >= 0:
            mine = code == cc
            cpk = float(A["peak"][mine].max()) if mine.any() else 0.0
            sold = float(tok[mine & ~buy & (ts > tau_entry)].sum())
            f["creator_sold_after"] = sold / cpk if cpk > 0 else None
        else:
            f["creator_sold_after"] = None
        i = int(np.searchsorted(ts, tau_entry, side="right")) - 1
        He = float(run[i]) if i >= 0 else 0.0
        f["insider_growth"] = (H - He) / SUPPLY
    return f


def flow_features(snap: C.AsOf, tau_entry: float | None = None) -> dict[str, Any] | None:
    """PLAN 4.4 seller features at snap.tau from B1 trades (ts <= tau). None when the coin has no B1 rows.

    ``ok = False`` with ``why`` when the prefix may be incomplete (beyond the B1 window, or at the 20,000-trade cap).
    ``tau_entry`` adds the exit features of the S1 exit set (org_net5, orphan_share10, creator_sold_after,
    insider_growth since tau_entry)."""
    tr = snap.trades
    if tr is None:
        return None
    if snap.tau > snap.g + B1_HORIZON_S:
        return {"ok": False, "why": "beyond_b1_window"}
    if len(tr) >= B1_MAX_TRADES:
        return {"ok": False, "why": "b1_trade_cap"}
    st = static_of(snap)
    L, n, last = _ledger_for(snap.mint, tr)
    key = (snap.mint, n, last, snap.tau, st, tau_entry)
    hit = _FEATS.get(key)
    if hit is not None:
        return dict(hit)
    f = _features_from(L, L.arrays(n), st, snap.tau, tau_entry)
    _FEATS.put(key, f)
    return dict(f)


def classify(f: Mapping[str, Any] | None, cap_def: str = "strict") -> str:
    """CAP / DIST / MIXED (PLAN 4.4). A NULL input never satisfies a condition (fail closed)."""
    if not f or not f.get("ok"):
        return "NA"
    d = CAP_DEFS[cap_def]
    sopr, share, rem = f.get("sopr3"), f.get("ins_sell_share3"), f.get("insider_rem")
    if (sopr is not None and share is not None and rem is not None and sopr < d["sopr_max"]
            and share < d["ins_share_max"] and f["n_sellers3"] >= d["n_sellers_min"]
            and rem < d["insider_rem_max"] and f["org_buyers3"] >= d["org_buyers_min"]):
        return "CAP"
    if sopr is not None and share is not None and sopr > DIST_SOPR_MIN and share > DIST_INS_SHARE_MIN:
        return "DIST"
    return "MIXED"


# =========================================================================== E1 candle dip, G1 gate, universe


def p_floor(snap: C.AsOf) -> float | None:
    """k / (1e9 - burned)^2 with k = X * y after the last completed minute and burned ~ AGENT tokens bought
    (BOOST burns what it buys), estimated per minute as agent SOL x the minute's tokens-per-SOL of all buys."""
    b = snap.bars
    if len(b) == 0:
        return None
    k = float(b.X[-1] * b.y[-1])
    a = np.asarray(b.agent_buy_sol, float)
    bs, bt = np.asarray(b.buy_sol, float), np.asarray(b.buy_tok, float)
    m = np.isfinite(a) & (a > 0) & (bs > 0)
    burned = min(float((a[m] * bt[m] / bs[m]).sum()), 0.5 * SUPPLY)
    return k / (SUPPLY - burned) ** 2 if k > 0 else None


def e1_check(snap: C.AsOf) -> dict[str, Any]:
    """E1 at the minute close tau: dd15 >= 0.25, close >= 3 x p_floor, age >= 10 min, 15-min volume >= $1.5k."""
    age = snap.tau - snap.g
    price = snap.price
    hi = snap.max_high(E1_DD_WINDOW_S)
    dd = 1.0 - price / hi if hi > 0 else 0.0
    fl = p_floor(snap)
    fm = price / fl if fl else None
    vol = snap.vol_usd(E1_DD_WINDOW_S)
    nonflow = age >= E1_MIN_AGE_S and fm is not None and fm >= E1_FLOOR_MULT and vol >= E1_VOL_USD_15M
    return {"age_close_s": age, "dd15": dd, "floor_mult": fm, "vol_usd15": vol, "nonflow_ok": bool(nonflow),
            "event": bool(nonflow and dd >= E1_DD15)}


def _nn(*v) -> bool:
    return all(x is not None for x in v)


def g1_chain(snap: C.AsOf) -> dict[str, Any]:
    """PLAN 4.2 on-chain classes (G-chain), knowable from tau >= g + 420 (AGENT resolved): OPERATOR > FACTORY >
    COMPLETED > UNRESOLVED (a rule needs a NULL input) > ORGANIC. INSTANT = graduated <= 5 s after creation but
    not FACTORY (no B1 exists for it: P4 skips every instant graduate)."""
    if not snap.agent_resolved:
        raise C.NotYetKnown("G1 classes need AGENT presence decided (tau >= g + 420 s)")
    gd = snap.get("grad_delay_s")
    tb, nb = snap.get("w120_buy_sol"), snap.get("w120_n_buyers")
    top = snap.top_buyers("w120", exclude_agent=False) or ()
    aw = snap.get("agent_wallet") if snap.agent_detected else None
    ag = sum(w[1] for w in top if aw and w[0] == aw)
    amm_buy = None if tb is None else tb - ag
    amm_buyers = None if nb is None else nb - (1 if ag > 0 else 0)
    top5 = snap.top_share("w120", 5, exclude_agent=True)
    csol, top3, cbuy, ncb = (snap.get(k) for k in ("completer_sol", "curve_top3_buy_sol", "curve_buy_sol",
                                                   "curve_n_buyers"))
    comp_share = None if csol is None else csol / G1_COMPLETER_WINDOW_SOL
    top3_share = None if top3 is None or not cbuy else top3 / cbuy
    f = {"grad_delay_s": gd, "amm_buy_sol_2m": amm_buy, "amm_buyers_2m": amm_buyers, "amm_top5_share_2m": top5,
         "completer_share": comp_share, "curve_top3_share": top3_share, "n_curve_buyers": ncb}
    if _nn(amm_buy, amm_buyers) and amm_buy >= G1_OPERATOR_MIN_BUY_SOL and amm_buyers <= G1_OPERATOR_MAX_BUYERS:
        return {"class": "OPERATOR", **f}
    if gd is None:
        return {"class": "UNRESOLVED", **f}
    if gd <= G1_INSTANT_MAX_DELAY_S:
        if top5 is not None and top5 >= G1_FACTORY_MIN_TOP5:
            return {"class": "FACTORY", **f}
        return {"class": "INSTANT", **f}
    tests = [None if comp_share is None else comp_share >= G1_COMPLETED_SHARE,
             None if top3_share is None else top3_share >= G1_COMPLETED_TOP3,
             None if ncb is None else ncb < G1_COMPLETED_MIN_BUYERS]
    if any(t is True for t in tests):
        return {"class": "COMPLETED", **f}
    if any(t is None for t in tests):
        return {"class": "UNRESOLVED", **f}
    return {"class": "ORGANIC", **f}


def universe(snap: C.AsOf, require_b1: bool = True) -> tuple[bool, str]:
    """D1 coins: B1 rows present, creation scanned (roles need the curve phase), graduated > 5 s after creation,
    and G1-chain class ORGANIC (the gate flags FACTORY / COMPLETED; OPERATOR coins go to M1). Coin-level facts
    known by g + 420 s; call at tau >= g + 420."""
    if require_b1 and snap.trades is None:
        return False, "no_b1"
    if snap.get("curve_partial") is not False:
        return False, "no_creation_data"
    gd = snap.get("grad_delay_s")
    if gd is None:
        return False, "no_creation_data"
    if gd <= G1_INSTANT_MAX_DELAY_S:
        return False, "instant"
    cls = g1_chain(snap)["class"]
    if cls != "ORGANIC":
        return False, f"g1_{cls.lower()}"
    return True, ""


def placebo_eligible(snap: C.AsOf) -> bool:
    """Matched control (PLAN 3.4): a random D1-universe coin at a decision age within +-2 min of the signal's,
    meeting every NON-dip E1 filter (age, floor multiple, 15-min volume) inside the B1 decision window."""
    if snap.tau - snap.g < E1_MIN_AGE_S or snap.age_s > MAX_DECISION_AGE_S:
        return False
    if not universe(snap)[0]:
        return False
    tr = snap.trades
    if tr is None or len(tr) >= B1_MAX_TRADES:
        return False
    return e1_check(snap)["nonflow_ok"]


# =========================================================================== the strategy


def variant_params(v: str) -> dict[str, Any]:
    cap_def, exit_set = VARIANTS[v]
    return {"version": VERSION, "study": "strategy", "variant": v, "entry_class": "CAP", "cap_def": cap_def,
            "exit_set": exit_set}


def event_params(cls: str, hold_min: int) -> dict[str, Any]:
    entry, cap_def = ("CAP", "loose") if cls == "CAP_LOOSE" else (cls, "strict")
    return {"version": VERSION, "study": "event", "event_class": cls, "entry_class": entry, "cap_def": cap_def,
            "hold_min": int(hold_min)}


def exit_spec(p: Mapping[str, Any]) -> C.ExitSpec:
    if p["study"] == "event":
        return C.ExitSpec(max_hold_s=60.0 * p["hold_min"])
    if p["exit_set"] == "s1":
        return C.ExitSpec(trail_pct=S1X_TRAIL, max_hold_s=S1X_MAX_HOLD_S)
    return BRACKET


def _flow_exit(snap: C.AsOf, pos: C.PositionView) -> C.Exit | None:
    """S1 exit set (PLAN 4.3), flow part; the trail and the 90-min limit are mechanical. Placebo positions get the
    same rule (it needs only the decision time, never the signal's state)."""
    tau_e = pos.t_dec - C.DECISION_LAG_S
    f = flow_features(snap, tau_entry=tau_e)
    if not f or not f.get("ok"):
        return None
    if f["org_net5"] <= S1X_ORG_NET5_SOL:
        return C.Exit("org_net5")
    o10 = f["orphan_share10"]
    if o10 is not None and o10 > S1X_ORPHAN10:
        return C.Exit("orphan_share10")
    cs = f["creator_sold_after"]
    if cs is not None and cs >= S1X_CREATOR_SOLD:
        return C.Exit("creator_sold")
    if f["insider_growth"] > S1X_INSIDER_GROWTH:
        return C.Exit("insider_growth")
    return None


def d1_strategy(snap: C.AsOf, p: Mapping[str, Any], pos: C.PositionView | None):
    """One entry per coin at the first E1 event whose class matches ``entry_class`` (ALL = any class)."""
    if pos is not None:
        return _flow_exit(snap, pos) if p.get("exit_set") == "s1" else None
    if snap.tau - snap.g < E1_MIN_AGE_S:
        return None
    if snap.age_s > MAX_DECISION_AGE_S:
        return C.SKIP
    ok, _ = universe(snap)
    if not ok:
        return C.SKIP
    e = e1_check(snap)
    if not e["event"]:
        return None
    f = flow_features(snap)
    if f is None:
        return C.SKIP
    if not f["ok"]:
        return C.SKIP                     # the B1 prefix may be incomplete from here on: no more entries
    cls = classify(f, p["cap_def"])
    if p["entry_class"] != "ALL" and cls != p["entry_class"]:
        return None
    keep = ("sopr3", "ins_sell_share3", "n_sellers3", "full_exit_share3", "insider_rem", "org_buyers3")
    return C.Enter(exits=exit_spec(p), tag=cls,
                   state={"dd15": e["dd15"], "floor_mult": e["floor_mult"], **{k: f[k] for k in keep}})


def train_grid() -> list[tuple[str, dict]]:
    """Every (hypothesis, params) run on TRAIN: 3 strategy variants + 5 event classes x 3 horizons = 18 trials."""
    out = [(HYP, variant_params(v)) for v in VARIANTS]
    out += [(HYP_EVENT, event_params(c, h)) for c in EVENT_CLASSES for h in HORIZONS_MIN]
    return out


# =========================================================================== statistics


def _sv(x: Any) -> Any:
    if isinstance(x, (np.floating, np.integer)):
        x = x.item()
    if isinstance(x, float):
        if math.isnan(x):
            return None
        if math.isinf(x):
            return "inf" if x > 0 else "-inf"
    return x


def jsonable(o: Any) -> Any:
    if isinstance(o, Mapping):
        return {str(k): jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [jsonable(v) for v in o]
    if isinstance(o, np.ndarray):
        return [jsonable(v) for v in o.tolist()]
    if isinstance(o, (np.bool_,)):
        return bool(o)
    return _sv(o)


def diff_ci(a: pd.DataFrame, b: pd.DataFrame, B: int = BOOT_B, seed: int = 0) -> dict[str, Any]:
    """mean(a) - mean(b) of ``ret_net`` with a coin-clustered bootstrap: coins are resampled JOINTLY (a coin in both
    sets carries its trades in both). None-valued CIs when either side is empty."""
    ra, rb = a["ret_net"].to_numpy(float), b["ret_net"].to_numpy(float)
    out = {"n_a": int(len(ra)), "n_b": int(len(rb)), "coins_a": int(a["mint"].nunique()) if len(a) else 0,
           "coins_b": int(b["mint"].nunique()) if len(b) else 0,
           "mean_a": float(ra.mean()) if len(ra) else None, "mean_b": float(rb.mean()) if len(rb) else None,
           "diff": float(ra.mean() - rb.mean()) if len(ra) and len(rb) else None, "ci90": None, "ci95": None}
    if not len(ra) or not len(rb):
        return out
    coins = pd.Index(pd.unique(pd.concat([a["mint"], b["mint"]], ignore_index=True)))
    ia, ib = coins.get_indexer(a["mint"]), coins.get_indexer(b["mint"])
    nc = len(coins)
    sa, ca = np.bincount(ia, ra, nc), np.bincount(ia, minlength=nc).astype(float)
    sb, cb = np.bincount(ib, rb, nc), np.bincount(ib, minlength=nc).astype(float)
    rng = np.random.default_rng(seed)
    diffs = []
    step = max(1, int(2_000_000 // max(nc, 1)))
    for s in range(0, B, step):
        m = min(step, B - s)
        idx = rng.integers(0, nc, size=(m, nc))
        W = np.zeros((m, nc))
        np.add.at(W, (np.repeat(np.arange(m), nc), idx.ravel()), 1.0)
        na, nb = W @ ca, W @ cb
        ok = (na > 0) & (nb > 0)
        diffs.append(((W @ sa)[ok] / na[ok]) - ((W @ sb)[ok] / nb[ok]))
    d = np.concatenate(diffs) if diffs else np.zeros(0)
    if len(d) >= 100:
        out["ci90"] = [float(np.quantile(d, 0.05)), float(np.quantile(d, 0.95))]
        out["ci95"] = [float(np.quantile(d, 0.025)), float(np.quantile(d, 0.975))]
    return out


def stop_rule(cap: pd.DataFrame, dist: pd.DataFrame, B: int = BOOT_B) -> dict[str, Any]:
    """PLAN 4.4 / stop rule 4 on VAL at the primary horizon: KILL if CAP - DIST < 5 points; PASS if >= 10 points
    with the coin-clustered 95 % CI above 0; WEAK in between (not killed, but D1 cannot pass); UNDERPOWERED when
    either class has < 20 trades (the rule is not evaluated: D1 is not killed and cannot pass)."""
    d = diff_ci(cap, dist, B=B)
    if d["n_a"] < GATE_MIN_TRADES or d["n_b"] < GATE_MIN_TRADES:
        st = "UNDERPOWERED"
    elif d["diff"] < GATE_KILL_BELOW:
        st = "KILL"
    elif d["diff"] >= GATE_PASS_AT and d["ci95"] is not None and d["ci95"][0] > 0:
        st = "PASS"
    else:
        st = "WEAK"
    return {"status": st, "cap_minus_dist": d["diff"], "kill_below": GATE_KILL_BELOW, "pass_at": GATE_PASS_AT,
            "min_trades_each": GATE_MIN_TRADES, **d}


def shortlist_rule(rows: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """PREREG §7: among V1-V3 with >= 30 TRAIN trades from >= 20 coins, the top 2 by TRAIN mean net return.
    None qualifies -> the default [V1, V2] (the PLAN's primary rule and its loose version), flagged."""
    ok = [(v, r["mean"]) for v, r in rows.items()
          if r.get("n", 0) >= SHORTLIST_MIN_TRADES and r.get("n_coins", 0) >= SHORTLIST_MIN_COINS
          and r.get("mean") is not None]
    ok.sort(key=lambda x: (-x[1], x[0]))
    if ok:
        picks, why = [v for v, _ in ok[:2]], "top 2 by TRAIN mean among variants meeting the minimum sample"
        status = "SHORTLISTED"
    else:
        picks, why = ["V1", "V2"], "no variant met the minimum sample: PLAN default [V1, V2]"
        status = "SHORTLISTED_UNDERPOWERED"
    cap_def = VARIANTS[picks[0]][0]
    return {"status": status, "variants": picks, "why": why, "configs": [variant_params(v) for v in picks],
            "event_configs": [event_params("CAP_LOOSE" if cap_def == "loose" else "CAP", PRIMARY_HORIZON_MIN),
                              event_params("DIST", PRIMARY_HORIZON_MIN)]}


def val_select(rows: Mapping[str, Mapping[str, Any]], shortlist: list[str], gate: Mapping[str, Any]) -> dict:
    """PREREG §8: KILL -> no TEST. Otherwise the shortlisted config with the higher VAL mean among those with >= 15
    VAL trades (ties -> shortlist order); none with 15 -> the first shortlisted."""
    if gate["status"] == "KILL":
        return {"status": "KILLED", "selected": None, "why": "stop rule 4: CAP - DIST < 5 points on VAL"}
    ok = [(v, rows[v]["mean"]) for v in shortlist
          if rows.get(v, {}).get("n", 0) >= VAL_MIN_TRADES and rows[v].get("mean") is not None]
    if ok:
        best = max(ok, key=lambda x: (x[1], -shortlist.index(x[0])))[0]
        why = "higher VAL mean among shortlisted configs with >= 15 VAL trades"
    else:
        best, why = shortlist[0], "no shortlisted config has 15 VAL trades: the first shortlisted"
    return {"status": "SELECTED", "selected": best, "params": variant_params(best), "why": why,
            "gate_status": gate["status"]}


def d1_verdict(entry: Mapping[str, Any], gate: Mapping[str, Any], confirm: Mapping[str, Any] | None = None) -> dict:
    """Overall D1 verdict: the PLAN 3.5 entry bar on TEST AND the VAL gate (CAP - DIST >= 10 points, CI > 0);
    a CONFIRM run with mean <= 0 downgrades a PASS to FAIL."""
    ev = entry["verdict"]
    gs = gate["status"]
    if gs == "KILL":
        v, why = "KILLED", "stop rule 4"
    elif ev != "PASS":
        v, why = ev, f"entry bar on TEST: {ev}"
    elif gs == "PASS":
        v, why = "PASS", "entry bar PASS and VAL gate PASS"
    elif gs == "UNDERPOWERED":
        v, why = "INCOMPLETE", "entry bar PASS but the VAL gate was underpowered"
    else:
        v, why = "FAIL", "entry bar PASS but CAP - DIST on VAL < 10 points or its CI includes 0"
    if v == "PASS" and confirm is not None and confirm.get("mean") is not None and confirm["mean"] <= 0:
        v, why = "FAIL", "CONFIRM mean <= 0"
    return {"verdict": v, "why": why, "entry_verdict": ev, "gate_status": gs}


def summarize(res: C.Result, reveal: bool = True, B: int = BOOT_B) -> dict[str, Any]:
    if not reveal:
        return res.summary(B=200)
    s = res.summary(B=B)
    t = res.trades
    s["tags"] = t["tag"].value_counts().to_dict() if len(t) else {}
    s["by_tag"] = {k: C.describe(v, B=min(B, 2000)) for k, v in t.groupby("tag")} if len(t) else {}
    s["n_trials_total"] = res.meta.get("n_trials_total")
    s["config"] = res.meta.get("config")
    return s


# =========================================================================== data checks


def _read_flow() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    f = C.flow_dir()
    return tuple(C._read_parquet(f / n) for n in ("graduates.parquet", "b2_coins.parquet", "b2_bars.parquet"))


def b1_mints() -> set[str] | None:
    p = C.flow_dir() / "b1_trades.parquet"
    if not p.exists():
        return None
    return set(pd.read_parquet(p, columns=["mint"])["mint"].unique())


def b1_coverage(split: str) -> dict[str, Any]:
    """Counts only (no prices): usable coins of ``split`` that P4 should have collected (creation scanned, graduated
    > 5 s after creation), and how many have B1 rows."""
    g, c, b = _read_flow()
    ds = C.Dataset.from_frames(split, g, c, b, census=C.Census.load(), guard=False)
    co = ds.coins
    elig = co[(~co["curve_partial"].astype(bool)) & (co["grad_delay_s"].fillna(-1) > G1_INSTANT_MAX_DELAY_S)]
    have = b1_mints()
    n_have = int(elig["mint"].isin(have).sum()) if have is not None else 0
    return {"split": split, "b1_file": have is not None, "usable": int(len(co)), "b1_eligible": int(len(elig)),
            "with_b1": n_have, "frac": round(n_have / len(elig), 4) if len(elig) else 0.0,
            "coverage_complete": bool(ds.coverage.get("complete")), "coverage_usable": ds.coverage.get("usable"),
            "days_full": ds.coverage.get("days_full"), "days_expected": ds.coverage.get("days_expected"),
            "chain_hours_scanned_frac": ds.coverage.get("chain_hours_scanned_frac")}


def validation_gates() -> tuple[bool, list[str]]:
    """PLAN stop rule 1: V1-V4 must have passed (FLOW/validation.json)."""
    p = C.flow_dir() / "validation.json"
    try:
        v = json.loads(p.read_text())
    except (OSError, ValueError):
        return False, ["FLOW/validation.json missing"]
    bad = [f"{k}: {(v.get(k) or {}).get('pass')}" for k in ("V1", "V2", "V3", "V4")
           if not isinstance(v.get(k), dict) or v[k].get("pass") is not True]
    return not bad, bad


def check_data(split: str, allow_partial: bool = False) -> dict[str, Any]:
    cov = b1_coverage(split)
    problems = []
    if not cov["coverage_complete"]:
        problems.append(f"{split} B2 coverage incomplete ({cov['days_full']}/{cov['days_expected']} full days, "
                        f"{cov['chain_hours_scanned_frac']} of chain hours scanned)")
    if not cov["b1_file"]:
        problems.append("no b1_trades.parquet (backfill phase P4 has not run)")
    elif cov["frac"] < B1_MIN_COVERAGE:
        problems.append(f"B1 covers {cov['with_b1']}/{cov['b1_eligible']} eligible {split} coins "
                        f"(< {B1_MIN_COVERAGE:.0%})")
    gates_ok, bad = validation_gates()
    if not gates_ok:
        problems.append(f"validation gates not all PASS: {bad}")
    cov["problems"] = problems
    if problems and not allow_partial:
        raise StageRefused("data not ready: " + "; ".join(problems))
    return cov


# =========================================================================== stage bookkeeping


STAGES = ("status", "debug", "train", "val", "test", "confirm", "final")
STAGE_SPLIT = {"train": "train", "val": "val", "test": "test", "confirm": "confirm", "final": "final",
               "debug": "final_train"}
STAGE_ENV = {"test": "LAB2_ALLOW_TEST", "confirm": "LAB2_ALLOW_CONFIRM", "final": "LAB2_ALLOW_FINAL"}
FINAL_PARTS = ("final_train", "final_val", "final_test")


def _prereg_sha() -> str | None:
    p = d1_dir() / "PREREG.md"
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None


def _read(name: str) -> dict | None:
    p = d1_dir() / name
    return json.loads(p.read_text()) if p.exists() else None


def _ledger_runs(hyp: str, split: str) -> int:
    with C._ledger(None, write=False) as led:
        return sum(1 for r in led["runs"] if r["hypothesis"] == hyp and r["split"] == split and not r.get("debug"))


def _require_frozen() -> None:
    sha = _prereg_sha()
    lk = d1_dir() / "prereg.lock"
    if sha is None:
        raise StageRefused("D1/PREREG.md is missing")
    if not lk.exists():
        raise StageRefused("no TRAIN run yet (D1/prereg.lock missing): run --stage train first")
    if json.loads(lk.read_text())["sha256"] != sha:
        raise StageRefused("D1/PREREG.md changed after the first TRAIN run: that is a new version (new VERSION, "
                           "new trials), not an edit")


def _env(flag: str) -> None:
    if os.environ.get(flag) != "1":
        raise StageRefused(f"needs env {flag}=1 (set by whoever runs the judge; d1.py never sets it)")


def prerequisites(stage: str) -> None:
    """Raise StageRefused when ``stage`` may not run now (PREREG §10). Data readiness is checked separately."""
    if stage in ("status", "debug"):
        return
    if stage == "train":
        sha = _prereg_sha()
        if sha is None:
            raise StageRefused("write D1/PREREG.md before any TRAIN run")
        if _read("val.json") is not None or _ledger_runs(HYP, "val") or _ledger_runs(HYP_EVENT, "val"):
            raise StageRefused("D1 already ran on VAL: TRAIN is closed (a new TRAIN run could change the shortlist)")
        lk = d1_dir() / "prereg.lock"
        if lk.exists() and json.loads(lk.read_text())["sha256"] != sha:
            raise StageRefused("D1/PREREG.md changed after the first TRAIN run: that is a new version")
        return
    _require_frozen()
    if stage == "val":
        tr = _read("train.json")
        if tr is None or tr.get("status") not in ("SHORTLISTED", "SHORTLISTED_UNDERPOWERED"):
            raise StageRefused(f"VAL needs a complete TRAIN run that wrote a shortlist (TRAIN status: "
                               f"{None if tr is None else tr.get('status')})")
        for h in (HYP, HYP_EVENT):
            if not (C.shortlist_dir() / f"{h}.json").exists():
                raise StageRefused(f"no written VAL shortlist for {h} ({C.shortlist_dir() / (h + '.json')})")
        if _read("val.json") is not None or _ledger_runs(HYP, "val"):
            raise StageRefused("D1 already ran on VAL")
        return
    if stage == "test":
        v = _read("val.json")
        if v is None:
            raise StageRefused("TEST needs the VAL run first")
        if v.get("status") != "SELECTED":
            raise StageRefused(f"VAL status is {v.get('status')}: D1 does not go to TEST")
        if _read("test.json") is not None or _ledger_runs(HYP, "test"):
            raise StageRefused("D1 already had its one TEST run")
        _env("LAB2_ALLOW_TEST")
        return
    if stage == "confirm":
        if _read("test.json") is None or not _ledger_runs(HYP, "test"):
            raise StageRefused("CONFIRM needs the TEST run first")
        if _read("confirm.json") is not None or _ledger_runs(HYP, "confirm"):
            raise StageRefused("D1 already had its one CONFIRM run")
        _env("LAB2_ALLOW_CONFIRM")
        return
    if stage == "final":
        if _read("test.json") is None or not _ledger_runs(HYP, "test"):
            raise StageRefused("never FINAL before TEST")
        if _read("final.json") is not None or _ledger_runs(HYP, "final"):
            raise StageRefused("D1 already had its one FINAL run")
        _env("LAB2_ALLOW_FINAL")
        return
    raise ValueError(f"unknown stage {stage!r}")


def load_split(split: str) -> C.Dataset:
    """Module-level so tests can substitute small datasets. VAL is opened only after prerequisites() confirmed the
    written shortlists; backtest() re-checks every config against them."""
    return C.load(split, _internal=(split == "val"))


def _lock_prereg() -> None:
    lk = d1_dir() / "prereg.lock"
    if not lk.exists():
        lk.write_text(json.dumps({"sha256": _prereg_sha(), "version": VERSION, "locked_utc": C.utc_str(time.time())},
                                 indent=1))


def _write(stage: str, payload: Mapping[str, Any], md: str, frames: Mapping[str, pd.DataFrame] | None = None) -> None:
    d = d1_dir()
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{stage}.json").write_text(json.dumps(jsonable(payload), indent=1, sort_keys=False))
    (d / f"{stage}.md").write_text(md)
    for name, df in (frames or {}).items():
        if df is not None and len(df):
            df.to_parquet(d / f"{stage}_{name}.parquet", index=False)


def _run(fn: Callable, split: str, hyp: str, params: dict, ds: C.Dataset, *, placebo: bool = True,
         stress: Mapping[str, C.FillConfig] | None = None, ledger_path: Path | None = None) -> C.Result:
    t0 = time.time()
    res = C.backtest(fn, split, params, hypothesis=hyp, ds=ds, placebo=placebo, n_placebo=N_PLACEBO,
                     placebo_eligible=placebo_eligible if placebo else None, stress=stress, seed=0,
                     declarations=DECLARATIONS, ledger_path=ledger_path)
    res.meta["wall_s"] = round(time.time() - t0, 2)
    return res


def _frames_of(results: Mapping[str, C.Result]) -> dict[str, pd.DataFrame]:
    tr, pl, st = [], [], []
    for label, r in results.items():
        tr.append(r.trades.assign(run=label))
        if len(r.placebo):
            pl.append(r.placebo.assign(run=label))
        for k, v in r.stress.items():
            st.append(v.assign(run=label, stress=k))
    cat = lambda xs: pd.concat(xs, ignore_index=True) if xs else None  # noqa: E731
    return {"trades": cat(tr), "placebo": cat(pl), "stress": cat(st)}


def fill_sensitivity(ds: C.Dataset, params: dict, reveal: bool = True) -> dict[str, Any]:
    """The same config under the alternative minute-bar fill assumptions (no ledger entry: not a new trial)."""
    out = {}
    for name, cfg in (("worst_default", C.FillConfig()),
                      ("no_entry_bar_exits", C.FillConfig(entry_bar_exits=False)),
                      ("exit_delay_1_bar", C.FillConfig(exit_delay_bars=1)),
                      ("open_fills", C.FillConfig(entry_fill="open", exit_fill="open")),
                      ("rent_0.22", C.FillConfig(rent_usd=0.22))):
        t = C.run_trades(ds, d1_strategy, params, cfg)
        d = C.describe(t, B=1000)
        out[name] = d if reveal else {"n": d["n"], "n_coins": d["n_coins"]}
    return out


def _days(ds: C.Dataset) -> float:
    days = ds.coverage.get("days") or []
    hrs = sum(d.get("hours_in_split", 0) for d in days)
    return hrs / 24.0 if hrs else 0.0


# =========================================================================== stages


def stage_status() -> dict[str, Any]:
    out: dict[str, Any] = {"version": VERSION, "prereg_sha256": _prereg_sha(), "prereg_locked": (d1_dir() / "prereg.lock").exists(),
                           "n_trials_total": C.n_trials(), "train_grid": len(train_grid()), "splits": {}, "stages": {}}
    for s in ("train", "val", "test", "confirm", "final_train", "final_val", "final_test"):
        try:
            out["splits"][s] = b1_coverage(s)
        except Exception as e:  # noqa: BLE001  (status must never crash)
            out["splits"][s] = {"error": repr(e)}
    for st in ("train", "val", "test", "confirm", "final"):
        try:
            prerequisites(st)
            out["stages"][st] = "prerequisites met (data checked at run time)"
        except StageRefused as e:
            out["stages"][st] = f"refused: {e}"
    gok, bad = validation_gates()
    out["validation_gates_ok"], out["validation_problems"] = gok, bad
    md = ["# D1 status", "", f"- version `{VERSION}`, PREREG locked: {out['prereg_locked']}, trials so far: "
          f"{out['n_trials_total']}", "", "| split | usable | B1-eligible | with B1 | B2 complete |", "|---|---:|---:|---:|---|"]
    for s, c in out["splits"].items():
        if "error" in c:
            md.append(f"| {s} | error | | | |")
        else:
            md.append(f"| {s} | {c['usable']} | {c['b1_eligible']} | {c['with_b1']} | {c['coverage_complete']} |")
    md += ["", "| stage | state |", "|---|---|"] + [f"| {k} | {v} |" for k, v in out["stages"].items()]
    _write("status", out, "\n".join(md) + "\n")
    return out


def stage_train(allow_partial: bool = False) -> dict[str, Any]:
    prerequisites("train")
    cov = check_data("train", allow_partial=allow_partial)
    partial = bool(cov["problems"])
    ds = load_split("train")
    _lock_prereg()
    results: dict[str, C.Result] = {}
    events: dict[str, dict] = {}
    for hyp, p in train_grid():
        if p["study"] == "event":
            label = f"{p['event_class']}@{p['hold_min']}"
            r = _run(d1_strategy, "train", hyp, p, ds)
            events[label] = summarize(r)
        else:
            label = p["variant"]
            r = _run(d1_strategy, "train", hyp, p, ds, stress={"costs_x1.5": C.FillConfig().stressed(1.5)})
        results[label] = r
    variants = {v: summarize(results[v]) for v in VARIANTS}
    sens = {v: fill_sensitivity(ds, variant_params(v)) for v in VARIANTS}
    contrasts = {}
    for h in HORIZONS_MIN:
        dist = results[f"DIST@{h}"].trades
        for c in ("CAP", "CAP_LOOSE"):
            contrasts[f"{c}-DIST@{h}"] = diff_ci(results[f"{c}@{h}"].trades, dist)
        contrasts[f"CAP-ALL@{h}"] = diff_ci(results[f"CAP@{h}"].trades, results[f"ALL@{h}"].trades)
    sl = shortlist_rule(variants)
    status = "PARTIAL" if partial else sl["status"]
    if not partial:
        C.write_shortlist(HYP, sl["configs"], note=f"{VERSION} TRAIN rule: {sl['why']}")
        C.write_shortlist(HYP_EVENT, sl["event_configs"], note=f"{VERSION} VAL gate (stop rule 4) at "
                                                               f"{PRIMARY_HORIZON_MIN} min")
    days = _days(ds)
    payload = {"stage": "train", "version": VERSION, "status": status, "coverage": cov, "days": days,
               "n_coins": len(ds), "events": events, "variants": variants, "fill_sensitivity": sens,
               "contrasts": contrasts, "shortlist": sl if not partial else {"not_written": cov["problems"], **sl},
               "trades_per_day": {k: (v.get("n", 0) / days if days else None) for k, v in variants.items()},
               "n_trials_total": C.n_trials(), "wall_s": {k: r.meta.get("wall_s") for k, r in results.items()}}
    _write("train", payload, _md_train(payload), _frames_of(results))
    return payload


def stage_val() -> dict[str, Any]:
    prerequisites("val")
    cov = check_data("val")
    tr = _read("train.json")
    sl = tr["shortlist"]
    ds = load_split("val")
    results: dict[str, C.Result] = {}
    for p in sl["event_configs"]:
        results[f"{p['event_class']}@{p['hold_min']}"] = _run(d1_strategy, "val", HYP_EVENT, p, ds)
    cap_label = next(k for k in results if k.startswith("CAP"))
    gate = stop_rule(results[cap_label].trades, results[f"DIST@{PRIMARY_HORIZON_MIN}"].trades)
    rows = {}
    for v in sl["variants"]:
        results[v] = _run(d1_strategy, "val", HYP, variant_params(v), ds)
        rows[v] = summarize(results[v])
    sel = val_select(rows, sl["variants"], gate)
    payload = {"stage": "val", "version": VERSION, "status": sel["status"], "coverage": cov, "gate": gate,
               "events": {k: summarize(results[k]) for k in results if "@" in k}, "variants": rows,
               "selection": sel, "n_trials_total": C.n_trials()}
    _write("val", payload, _md_val(payload), _frames_of(results))
    return payload


def _val_result(variant: str) -> C.Result | None:
    p = d1_dir() / "val_trades.parquet"
    if not p.exists():
        return None
    t = pd.read_parquet(p)
    t = t[t["run"] == variant].drop(columns=["run"])
    return C.Result(trades=t, placebo=t.iloc[0:0], stress={}, meta={"split": "val", "hypothesis": HYP})


def _oos(stage: str) -> tuple[dict[str, Any], C.Result]:
    prerequisites(stage)
    split = STAGE_SPLIT[stage]
    cov = {s: check_data(s) for s in (FINAL_PARTS if split == "final" else (split,))}
    val = _read("val.json")
    sel = val["selection"]["selected"]
    params = variant_params(sel)
    ds = load_split(split)
    res = _run(d1_strategy, split, HYP, params, ds)       # stress costs x1.5 is the default on one-run splits
    out = {"stage": stage, "version": VERSION, "split": split, "coverage": cov, "selected": sel, "params": params,
           "summary": summarize(res), "fill_sensitivity": fill_sensitivity(ds, params),
           "rejections": C.auto_rejections(res), "n_trials_total": C.n_trials(), "gate": val["gate"]}
    return out, res


def stage_test() -> dict[str, Any]:
    out, res = _oos("test")
    val = _read("val.json")
    entry = C.verdict_entry(res, val=_val_result(out["selected"]))
    out["entry_verdict"] = entry
    out["d1_verdict"] = d1_verdict(entry, val["gate"])
    out["status"] = out["d1_verdict"]["verdict"]
    _write("test", out, _md_oos(out), _frames_of({out["selected"]: res}))
    return out


def stage_confirm() -> dict[str, Any]:
    out, res = _oos("confirm")
    test = _read("test.json")
    s = out["summary"]
    out["confirm_consistent"] = s.get("mean") is not None and s["mean"] > 0
    out["d1_verdict"] = d1_verdict(test["entry_verdict"], test["gate"], confirm=s)
    out["status"] = out["d1_verdict"]["verdict"]
    _write("confirm", out, _md_oos(out), _frames_of({out["selected"]: res}))
    return out


def stage_final() -> dict[str, Any]:
    out, res = _oos("final")
    test = _read("test.json")
    tres_p = d1_dir() / "test_trades.parquet"
    t = pd.read_parquet(tres_p).drop(columns=["run"])
    pl = d1_dir() / "test_placebo.parquet"
    st = d1_dir() / "test_stress.parquet"
    tres = C.Result(trades=t, placebo=pd.read_parquet(pl).drop(columns=["run"]) if pl.exists() else t.iloc[0:0],
                    stress={k: v.drop(columns=["run", "stress"]) for k, v in pd.read_parquet(st).groupby("stress")}
                    if st.exists() else {}, meta={"split": "test", "hypothesis": HYP, "declarations": DECLARATIONS})
    entry = C.verdict_entry(tres, val=_val_result(out["selected"]), final=res)
    conf = _read("confirm.json")
    out["entry_verdict_with_final"] = entry
    out["d1_verdict"] = d1_verdict(entry, test["gate"], confirm=(conf or {}).get("summary"))
    out["status"] = out["d1_verdict"]["verdict"]
    _write("final", out, _md_oos(out), _frames_of({out["selected"]: res}))
    return out


# =========================================================================== debug (census TRAIN third; counts only)


def synth_b1(ds: C.Dataset, mints: Iterable[str], seed: int = 0) -> pd.DataFrame:
    """SYNTHETIC B1 tapes shaped by each coin's real minute bars, ONLY to exercise the pipeline end to end.

    Read through AsOf at the end of the coin's window (data generation, not a strategy feature). Wallet roles
    (insider vs organic sellers, orphan sellers) are random per coin, so class counts on these tapes mean
    nothing; they are never reported as estimates."""
    rows = []
    v0 = 17.584505289
    for m in mints:
        cd_snap = ds.asof(m, ds.coin(m).g + 60 * C.N_BARS + 60)
        rng = np.random.default_rng([seed, abs(hash(m)) % (2 ** 32)])
        g = cd_snap.g
        created = cd_snap.get("created_ts")
        c_slot = cd_snap.get("c_slot")
        if created is None or c_slot is None:
            continue
        slot_of = lambda t: int(c_slot + (t - created) * 2.5)  # noqa: E731
        q_ins, q_orph = rng.uniform(0.0, 0.8), rng.uniform(0.0, 0.08)
        hold: dict[int, float] = {}
        ins_set: set[int] = set()
        nxt = [10_000]

        def new_w() -> int:
            nxt[0] += 1
            return nxt[0]

        def add(t, venue, buy, w, sol, tok, x0, y0, virt=0.0):
            if sol < 0.01:
                return
            rows.append({"slot": slot_of(t), "tx_idx": len(rows) % 400, "pix": 0, "ix": 0, "ts": int(t), "mint": m,
                         "venue": venue, "is_buy": bool(buy), "wallet_h": np.uint64(w), "usol": int(sol * LAMPORTS),
                         "tok": int(tok * TOK), "x0": int(x0 * LAMPORTS), "y0": int(y0 * TOK), "fees": 0,
                         "virt_ksol": int(virt * 1e6), "src": 9})
            hold[w] = hold.get(w, 0.0) + (tok if buy else -tok)

        X, Y = 30.0, 1.073e9
        curve_w = []
        creator = wallet_h(cd_snap.get("creator")) or new_w()
        completer = wallet_h(cd_snap.get("completer30")) or new_w()
        plan = [(created, creator, 1.0), (created, new_w(), 1.5), (created, new_w(), 1.5)]
        span = max(g - created - 10, 60)
        for _ in range(40):
            plan.append((created + rng.uniform(1, span), new_w(), rng.uniform(0.3, 2.5)))
        plan.sort(key=lambda r: r[0])
        for t, w, s in plan:
            if X - 30 >= 80:
                break
            tok = Y - X * Y / (X + s)
            add(t, 0, True, w, s, tok, X, Y)
            X, Y = X + s, Y - tok
            curve_w.append(w)
        s = max(85.0 - (X - 30), 0.5)
        tok = Y - X * Y / (X + s)
        add(g - 1, 0, True, completer, s, tok, X, Y)
        ins_set.update(curve_w[:20] + [creator, completer])
        b = cd_snap.bars
        org_pool: list[int] = []
        agent = wallet_h(cd_snap.get("agent_wallet")) if cd_snap.agent_detected else None
        for j in range(len(b)):
            t0 = int(b.minute_ts[j])
            if t0 + 60 > g + B1_HORIZON_S or not b.traded[j]:
                continue
            px = float(b.c[j])
            Xj, yj = float(b.X[j]), float(b.y[j])
            nb, ns = int(min(b.n_buys[j], 30)), int(min(b.n_sells[j], 30))
            ag = float(b.agent_buy_sol[j]) if np.isfinite(b.agent_buy_sol[j]) else 0.0
            if agent is not None and ag > 0.01:
                add(t0 + 5, 1, True, agent, ag, ag / px, Xj - v0, yj, v0)
            if nb:
                for sz, tt in zip(rng.dirichlet(np.ones(nb)) * max(float(b.buy_sol[j]) - ag, 0.0),
                                  np.sort(rng.uniform(t0, t0 + 59, nb))):
                    w = org_pool[int(rng.integers(len(org_pool)))] if org_pool and rng.random() < 0.3 else new_w()
                    org_pool.append(w)
                    add(tt, 1, True, w, float(sz), float(sz) / px, Xj - v0, yj, v0)
            for tt in np.sort(rng.uniform(t0, t0 + 59, ns)):
                if rng.random() < q_orph:
                    w, q = new_w(), rng.uniform(1e5, 5e6)
                else:
                    pool = [w for w in (ins_set if rng.random() < q_ins else org_pool) if hold.get(w, 0) > 1]
                    if not pool:
                        continue
                    w = pool[int(rng.integers(len(pool)))]
                    q = hold[w] * rng.uniform(0.2, 1.0)
                add(tt, 1, False, w, q * px * rng.uniform(0.95, 1.0), q, Xj - v0, yj, v0)
    df = pd.DataFrame(rows)
    if len(df):
        df["wallet_h"] = df["wallet_h"].astype(np.uint64)
        df = df.sort_values(["mint", "slot", "tx_idx"], kind="stable").reset_index(drop=True)
    return df


def e1_scan(ds: C.Dataset, require_b1: bool = False) -> dict[str, Any]:
    """Counts of E1 events (bars only) on D1-universe coins, decision grid t = minute boundary + 20 s, age at the
    minute close in [10 min, 120 min). Also bar-level UPPER BOUNDS for the CAP sample-size conditions: the sum of
    per-minute distinct sellers (buyers) over the last 3 minutes bounds n_sellers3 (org_buyers3) from above."""
    uni_reasons: dict[str, int] = {}
    n_events = 0
    coins_any = coins_ub_strict = coins_ub_loose = 0
    ev_ub_strict = ev_ub_loose = 0
    first_age = []
    for m in ds.mints:
        cd = ds.coin(m)
        snap0 = ds.asof(m, cd.g + E1_MIN_AGE_S + 60)
        ok, why = universe(snap0, require_b1=require_b1)
        uni_reasons[why or "eligible"] = uni_reasons.get(why or "eligible", 0) + 1
        if not ok:
            continue
        got = got_s = got_l = False
        for j in range(1, C.N_BARS):
            t = cd.bar_start(j) + C.GRID_OFFSET_S
            if t - cd.g > MAX_DECISION_AGE_S:
                break
            snap = ds.asof(m, t)
            if snap.tau - snap.g < E1_MIN_AGE_S:
                continue
            e = e1_check(snap)
            if not e["event"]:
                continue
            n_events += 1
            if not got:
                first_age.append(snap.tau - snap.g)
            got = True
            b = snap.bars
            ns, nb = float(b.n_sellers[-3:].sum()), float(b.n_buyers[-3:].sum())
            if ns >= CAP_DEFS["strict"]["n_sellers_min"] and nb >= CAP_DEFS["strict"]["org_buyers_min"]:
                ev_ub_strict += 1
                got_s = True
            if ns >= CAP_DEFS["loose"]["n_sellers_min"] and nb >= CAP_DEFS["loose"]["org_buyers_min"]:
                ev_ub_loose += 1
                got_l = True
        coins_any += got
        coins_ub_strict += got_s
        coins_ub_loose += got_l
    return {"universe": uni_reasons, "eligible_coins": uni_reasons.get("eligible", 0), "e1_events": n_events,
            "coins_with_e1": coins_any, "e1_events_cap_feasible_ub_strict": ev_ub_strict,
            "e1_events_cap_feasible_ub_loose": ev_ub_loose, "coins_cap_feasible_ub_strict": coins_ub_strict,
            "coins_cap_feasible_ub_loose": coins_ub_loose,
            "first_e1_age_min_quartiles": [round(float(q) / 60, 1) for q in np.quantile(first_age, [0.25, 0.5, 0.75])]
            if first_age else None}


def stage_debug() -> dict[str, Any]:
    """Census TRAIN third (final_train, PLAN 3.1 debug-only): real E1 event counts (bars), then the full pipeline on
    SYNTHETIC B1 tapes for mechanics and timing. Never reports a return; runs go to a throwaway ledger."""
    t0 = time.time()
    ds = C.load("final_train")
    days_created = (ds.coins["created_for_split"].max() - ds.coins["created_for_split"].min()) / 86400.0
    scan = e1_scan(ds, require_b1=False)
    per_day = {k: round(scan[k] / days_created, 1) for k in ("eligible_coins", "e1_events", "coins_with_e1",
                                                              "coins_cap_feasible_ub_strict",
                                                              "coins_cap_feasible_ub_loose")}
    t_scan = time.time() - t0
    real_b1 = b1_mints()
    real_b1_here = len(set(ds.mints) & real_b1) if real_b1 else 0
    g, c, b = _read_flow()
    elig = [m for m in ds.mints if universe(ds.asof(m, ds.coin(m).g + 700), require_b1=False)[0]]
    tr = synth_b1(ds, elig)
    dsx = C.Dataset.from_frames("final_train", g, c, b, census=C.Census.load(), sol=ds.sol, trades=tr, guard=False)
    runs = {}
    with tempfile.TemporaryDirectory() as tmp:
        led = Path(tmp) / "trials_debug.json"
        for hyp, p in train_grid():
            t1 = time.time()
            r = _run(d1_strategy, "final_train", hyp, p, dsx, ledger_path=led)
            s = r.summary()                  # debug split: counts only (returns hidden by common)
            label = p.get("variant") or f"{p['event_class']}@{p['hold_min']}"
            runs[label] = {"n": s["n"], "n_coins": s["n_coins"], "n_placebo": s["n_placebo"], "reasons": s["reasons"],
                           "tags": r.trades["tag"].value_counts().to_dict() if len(r.trades) else {},
                           "wall_s": round(time.time() - t1, 2)}
    payload = {"stage": "debug", "split": "final_train", "version": VERSION,
               "created_span_days": round(days_created, 3), "usable_coins": len(ds), "e1_scan_real_bars": scan,
               "per_day_real_bars": per_day, "real_b1_coins_in_split": real_b1_here,
               "synthetic_b1": {"coins": len(elig), "trades": int(len(tr)),
                                "note": "SYNTHETIC tapes: class counts and trades are pipeline checks, not estimates"},
               "runs_on_synthetic_b1": runs, "wall_s": {"e1_scan": round(t_scan, 1), "total": round(time.time() - t0, 1)}}
    _write("debug", payload, _md_debug(payload))
    return payload


# =========================================================================== markdown


def _pct(x: Any, nd: int = 1) -> str:
    return "n/a" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{100 * x:+.{nd}f}%"


def _ci(ci: Any) -> str:
    return "n/a" if not ci else f"[{100 * ci[0]:+.1f}, {100 * ci[1]:+.1f}]"


def _row(label: str, s: Mapping[str, Any]) -> str:
    pc = s.get("placebo") or {}
    return (f"| {label} | {s.get('n', 0)} | {s.get('n_coins', 0)} | {_pct(s.get('mean'))} | {_pct(s.get('median'))} | "
            f"{_ci(s.get('ci90'))} | {_pct(s.get('mean_without_top2'))} | {_pct(pc.get('mean_diff'))} |")


_HDR = ["| run | trades | coins | mean | median | 90% CI | mean w/o top 2 | vs placebo |",
        "|---|---:|---:|---:|---:|---|---:|---:|"]


def _md_train(p: Mapping[str, Any]) -> str:
    md = [f"# D1 TRAIN ({p['version']})", "", f"**Status: {p['status']}**", ""]
    if p["coverage"].get("problems"):
        md += ["Data problems (preview only, no shortlist written):", ""] + [f"- {x}" for x in p["coverage"]["problems"]] + [""]
    md += ["## Strategy variants (worst fills, $20, costs as of the trade date)", ""] + _HDR
    md += [_row(k, v) for k, v in p["variants"].items()]
    md += ["", "## Event study (first event of the class per coin, fixed hold)", ""] + _HDR
    md += [_row(k, v) for k, v in p["events"].items()]
    md += ["", "## Contrasts (coin-clustered)", "", "| contrast | diff | 95% CI | n a / n b |", "|---|---:|---|---|"]
    md += [f"| {k} | {_pct(v['diff'])} | {_ci(v['ci95'])} | {v['n_a']} / {v['n_b']} |" for k, v in p["contrasts"].items()]
    sl = p["shortlist"]
    md += ["", f"## Shortlist: {sl['variants']} ({sl['why']})", "", f"Trials so far: {p['n_trials_total']}", ""]
    return "\n".join(md)


def _md_val(p: Mapping[str, Any]) -> str:
    g = p["gate"]
    md = [f"# D1 VAL ({p['version']})", "", f"**Status: {p['status']}** (gate {g['status']}: CAP - DIST = "
          f"{_pct(g['cap_minus_dist'])}, 95% CI {_ci(g['ci95'])}, n {g['n_a']} / {g['n_b']})", ""] + _HDR
    md += [_row(k, v) for k, v in {**p["events"], **p["variants"]}.items()]
    md += ["", f"Selection: {p['selection']}", ""]
    return "\n".join(md)


def _md_oos(p: Mapping[str, Any]) -> str:
    md = [f"# D1 {p['stage'].upper()} ({p['version']})", "", f"**D1 verdict: {p['d1_verdict']['verdict']}** "
          f"({p['d1_verdict']['why']})", ""] + _HDR + [_row(p["selected"], p["summary"])]
    ev = p.get("entry_verdict") or p.get("entry_verdict_with_final")
    if ev:
        md += ["", "| # | criterion | pass | value | need |", "|---|---|---|---|---|"]
        md += [f"| {c['id']} | {c['name']} | {c['pass']} | {c['value']} | {c['need']} |" for c in ev["criteria"]]
    md += ["", f"Auto-rejections: {p['rejections'] or 'none'}", ""]
    return "\n".join(md)


def _md_debug(p: Mapping[str, Any]) -> str:
    s, d = p["e1_scan_real_bars"], p["per_day_real_bars"]
    md = ["# D1 debug (census TRAIN third, counts only)", "",
          f"- Coins created over {p['created_span_days']} days; usable {p['usable_coins']}; universe {s['universe']}",
          f"- Real-bar E1 events: {s['e1_events']} on {s['coins_with_e1']} coins; first-event age quartiles (min) "
          f"{s['first_e1_age_min_quartiles']}",
          f"- Per day: {d}",
          f"- CAP-feasible upper bound (bars): strict {s['coins_cap_feasible_ub_strict']} coins, loose "
          f"{s['coins_cap_feasible_ub_loose']} coins",
          f"- Real B1 coins in this split: {p['real_b1_coins_in_split']}",
          "", "## Pipeline on SYNTHETIC B1 (mechanics only)", "",
          "| run | trades | coins | placebo | tags | exit reasons | wall s |", "|---|---:|---:|---:|---|---|---:|"]
    md += [f"| {k} | {v['n']} | {v['n_coins']} | {v['n_placebo']} | {v['tags']} | {v['reasons']} | {v['wall_s']} |"
           for k, v in p["runs_on_synthetic_b1"].items()]
    return "\n".join(md) + "\n"


# =========================================================================== CLI


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stage", choices=STAGES, required=True)
    ap.add_argument("--allow-partial", action="store_true",
                    help="TRAIN only: run on incomplete data as a preview (no shortlist is written)")
    a = ap.parse_args(argv)
    fn = {"status": stage_status, "debug": stage_debug, "val": stage_val, "test": stage_test,
          "confirm": stage_confirm, "final": stage_final}
    try:
        out = stage_train(a.allow_partial) if a.stage == "train" else fn[a.stage]()
    except StageRefused as e:
        print(f"REFUSED ({a.stage}): {e}", file=sys.stderr)
        return 2
    except C.SplitLocked as e:
        print(f"REFUSED ({a.stage}): {e}", file=sys.stderr)
        return 2
    print(json.dumps({"stage": a.stage, "status": out.get("status"), "written": str(d1_dir() / f"{a.stage}.json")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
