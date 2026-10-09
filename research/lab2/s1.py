"""S1 (PLAN §4.3): buy once the insiders' cheap inventory is spent (BOOST-aware supply overhang).

Research only (wave-2 lab). Pre-registration: ``research/lab2/S1/PREREG.md`` (frozen at the first TRAIN run).

THE ONE RULE OF THIS FILE: every feature comes through ``common.AsOf`` -- static fields via ``snap[...]`` at their
legal time, raw trades via ``snap.trades`` (B1 rows with ts <= tau), bars via ``snap.alive()``. Nothing here reads a
``Dataset``/``CoinData`` column directly, so the common.py lookahead rules (and their tests) cover S1 too.

Why B1 is mandatory: S1's features are WALLET-LEVEL (who holds the cheap curve inventory, who sells tokens they
never bought, which buyers are organic). Minute bars carry no wallet roles; from bars, ``insider_rem`` is only
bounded by how far the price sits above its floor (the killed FL1 idea), so no bar-only proxy runs as "S1".

CLI::

    python research/lab2/s1.py --stage status                 # data coverage, prerequisites, trial counts
    python research/lab2/s1.py --stage debug                  # census TRAIN third, counts only (synthetic B1 if none)
    python research/lab2/s1.py --stage train [--allow-partial]
    python research/lab2/s1.py --stage val
    LAB2_ALLOW_TEST=1    python research/lab2/s1.py --stage test
    LAB2_ALLOW_CONFIRM=1 python research/lab2/s1.py --stage confirm
    LAB2_ALLOW_FINAL=1   python research/lab2/s1.py --stage final

Each stage writes ``S1/<stage>.json`` + ``S1/<stage>.md`` (+ raw trades as parquet) and REFUSES to run when its
prerequisites are missing (exit code 2).
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
import time
import warnings
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import common as C  # noqa: E402

VERSION = "s1-v1"
HYP, HYP_GATE, HYP_CTRL = "S1", "S1-gate", "S1-control1"


def s1_dir() -> Path:
    return Path(os.environ.get("LAB2_S1_DIR", str(HERE / "S1")))


# =========================================================================== constants (PREREG §3-§9)

CHECKPOINTS_MIN = (6, 8, 10, 15, 20, 30, 45, 60, 90, 120)
GATE_CHECKPOINTS_MIN = (10, 30)
GATE_HOLD_S = 1800
B1_HORIZON_S = 7200            # B1 (P4b) window = [created, g + 120 min)
B1_MAX_TRADES: int | None = None   # P4b (backfill) never truncates; None skips the check (P4 cut at 20,000)
SUPPLY = 1e9                   # whole tokens
TOK = 1e6                      # raw token units per whole token
LAMPORTS = 1e9
CURVE_BAND = (55.0, 85.0)      # COMPLETER: real SOL band (the last 30 SOL)
SNIPER_WINDOW_S, SNIPER_FIRST_N = 60, 20
ORPHAN_TOL = 0.02              # orphan part counts only above 2 % of the sell (B1 drops dust buys)
BOT_MIN_TRADES, BOT_MEDIAN_HOLD_S, BOT_RT_S, BOT_MIN_RT = 4, 10.0, 60.0, 3
WASH_S, WASH_REL = 60.0, 0.05
MECH_WINDOW_S, MECH_MIN_BUYS, MECH_MAX_SELL_FRAC = 1800, 6, 0.10
MECH_GAP_CV, MECH_SIZE_CV, MECH_SPEARMAN = 0.25, 0.5, 0.3
BOOST_WINDOW_S = 300
G1_AT_S = 120
OPERATOR_BUY_SOL, OPERATOR_MAX_BUYERS = 500.0, 30
FACTORY_DELAY_S, FACTORY_TOP5 = 5.0, 0.85
COMPLETED_SHARE, COMPLETED_TOP3, COMPLETED_MIN_BUYERS = 0.6, 0.6, 15
ALLOWED_CLASSES = ("ORGANIC", "COMPLETED")   # NEWS needs metadata: merged into ORGANIC (both allowed)

THETA_REM = (0.10, 0.25)
THETA_BUY = (10, 20)
ABSORB_REQ = (True, False)

# gate / selection minimums (PREREG §7, §11)
GATE_MIN_COINS = {"train": 100, "val": 50}
GATE_VAL_MIN_SPREAD = 0.05
SHORTLIST_MIN_TRADES, SHORTLIST_MIN_COINS = 30, 20
CONTROL_MARGIN = 0.06
VAL_MIN_TRADES = 15
CTRL_MIN_TRADES_FOR_MARGIN = 20
B1_MIN_COVERAGE = 0.95

DECLARATIONS = {"uses_organic_flow": True, "organic_excludes": ["AGENT", "BOT", "WASH", "DUST", "MECH"],
                "uses_wallet_reputation": False, "uses_truncated_windows": False,
                "uses_current_state_fields": False,
                "notes": ["BOT has no registry part (no B3 registry)", "TRANSFEREE from orphan sells only",
                          "burned ~ AGENT tokens", "minute-bar worst fills (X1 not built)"]}


class StageRefused(RuntimeError):
    """A stage's prerequisites are missing (the CLI exits with code 2)."""


# =========================================================================== wallet hashing (ClickHouse cityHash64)

_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_M64 = (1 << 64) - 1
_K0, _K1, _K2, _K3 = 0xC3A5C85C97CB3127, 0xB492B66FBE98F273, 0x9AE16A3B2F90404F, 0xC949D7C7509E6557


def b58decode(s: str) -> bytes:
    n = 0
    for ch in s:
        n = n * 58 + _B58.index(ch)
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


def _h128to64(u: int, v: int) -> int:
    kmul = 0x9DDFEA08EB382D69
    a = ((u ^ v) * kmul) & _M64
    a ^= a >> 47
    b = ((v ^ a) * kmul) & _M64
    b ^= b >> 47
    return (b * kmul) & _M64


def cityhash64(b: bytes) -> int:
    """ClickHouse ``cityHash64`` (CityHash v1.0.2) for 17-32 byte strings (Solana keys are 32 bytes).
    Checked on 917/917 real (wallet_h, base58) pairs from B1 query results."""
    n = len(b)
    if not 17 <= n <= 32:
        raise ValueError("cityhash64 port covers 17-32 byte inputs only")
    f = lambda i: struct.unpack_from("<Q", b, i)[0]  # noqa: E731
    a = (f(0) * _K1) & _M64
    bb = f(8)
    c = (f(n - 8) * _K2) & _M64
    d = (f(n - 16) * _K0) & _M64
    return _h128to64((_rot((a - bb) & _M64, 43) + _rot(c, 30) + d) & _M64, (a + _rot(bb ^ _K3, 20) - c + n) & _M64)


def wallet_h(address: str) -> int:
    """B1 ``wallet_h`` of a base58 address (cityHash64 of the raw 32-byte key)."""
    return cityhash64(b58decode(address))


_POOLED_H: frozenset[int] | None = None


def pooled_hashes() -> frozenset[int]:
    global _POOLED_H
    if _POOLED_H is None:
        addrs = set(C.POOLED_ACCOUNTS) | C._pooled_from_file()
        _POOLED_H = frozenset(wallet_h(a) for a in addrs)
    return _POOLED_H


# =========================================================================== prefix-level ledger and roles


@dataclass
class _Prefix:
    """Everything derivable from a trade prefix alone (cached by content). Arrays are in chain order."""

    n: int
    ts: np.ndarray
    venue: np.ndarray
    buy: np.ndarray
    sol: np.ndarray            # user-side SOL
    tok: np.ndarray            # raw token units (int64)
    codes: np.ndarray          # wallet code per trade
    uw: np.ndarray             # wallet_h per code (sorted)
    pooled_w: np.ndarray
    pos_before: np.ndarray     # raw
    pos_after: np.ndarray
    pos_w: np.ndarray          # raw, per wallet
    peak_w: np.ndarray
    orphan: np.ndarray         # effective orphan part per trade (raw)
    transferee_w: np.ndarray
    bot_w: np.ndarray
    wash_w: np.ndarray
    agent: dict | None
    agent_code: int | None
    agent_tok: float
    creator_code: int | None
    completer_code: int | None
    completer_band_sol: float | None
    bundle_w: np.ndarray
    sniper_w: np.ndarray
    roles_known_ts: float
    ins_w: np.ndarray
    insider_hold: float        # tokens
    insider_peak: float        # tokens
    insider_cost_sol: float
    insider_pos_pos: float     # tokens (sum pos+ of INS wallets with cost tracked)
    p_pre: np.ndarray          # pool trades: SOL per token before the trade (nan elsewhere)
    p_post: np.ndarray
    y_post_last: float | None  # tokens in the pool after the last pool trade
    n_curve_buyers_seen: int


def _grouped(codes: np.ndarray):
    order = np.lexsort((np.arange(len(codes)), codes))
    cs = codes[order]
    start = np.r_[True, cs[1:] != cs[:-1]] if len(cs) else np.zeros(0, bool)
    gstart = np.maximum.accumulate(np.where(start, np.arange(len(cs)), 0)) if len(cs) else np.zeros(0, np.int64)
    return order, cs, gstart


def _build_prefix(tr: pd.DataFrame, st: dict, g: float) -> _Prefix:
    n = len(tr)
    ts = tr["ts"].to_numpy(np.int64)
    venue = tr["venue"].to_numpy(np.int64)
    buy = tr["is_buy"].to_numpy().astype(bool)
    sol = tr["usol"].to_numpy(np.float64) / LAMPORTS
    tok = tr["tok"].to_numpy(np.int64)
    fees = tr["fees"].to_numpy(np.float64) / LAMPORTS if "fees" in tr else np.zeros(n)
    x0 = tr["x0"].to_numpy(np.float64)
    y0 = tr["y0"].to_numpy(np.float64)
    virt = tr["virt_ksol"].to_numpy(np.float64) * 1000.0 if "virt_ksol" in tr else np.zeros(n)
    slot = tr["slot"].to_numpy(np.int64)
    w = tr["wallet_h"].to_numpy(np.uint64)
    uw, codes = np.unique(w, return_inverse=True)
    codes = codes.astype(np.int64)
    W = len(uw)
    pooled_w = np.isin(uw, np.array(sorted(pooled_hashes()), dtype=np.uint64))
    if "pooled" in tr:
        pt = tr["pooled"].to_numpy().astype(bool)
        if pt.any():
            pooled_w[np.unique(codes[pt])] = True
    pool_t = pooled_w[codes]

    # ---- ledger (raw token units, exact integers)
    d = np.where(buy, tok, -tok)
    order, cs, gstart = _grouped(codes)
    ds_ = d[order]
    csum = np.cumsum(ds_)
    off = csum[gstart] - ds_[gstart] if n else csum
    pa_s = csum - off
    pos_after = np.empty(n, np.int64)
    pos_after[order] = pa_s
    pos_before = pos_after - d
    pos_w = np.zeros(W, np.int64)
    np.add.at(pos_w, codes, d)
    peak_w = np.zeros(W, np.int64)
    np.maximum.at(peak_w, codes, pos_after)
    orphan = np.where(~buy, np.maximum(0, tok - np.maximum(pos_before, 0)), 0)
    orphan = np.where((orphan > ORPHAN_TOL * tok) & ~pool_t, orphan, 0)
    transferee_w = np.zeros(W, bool)
    transferee_w[np.unique(codes[orphan > 0])] = True

    # ---- BOT / WASH (per wallet, chain order)
    ts_s, buy_s, tok_s = ts[order], buy[order], tok[order]
    idx = np.arange(n)
    lb = np.maximum.accumulate(np.where(buy_s, idx, -1)) if n else idx
    ls = np.maximum.accumulate(np.where(~buy_s, idx, -1)) if n else idx
    vlb = (lb >= gstart) & ~buy_s
    vls = (ls >= gstart) & buy_s
    hold = np.where(vlb, ts_s - ts_s[np.maximum(lb, 0)], np.nan)
    n_tr_w = np.bincount(codes, minlength=W)
    bot_w = np.zeros(W, bool)
    if vlb.any():
        hc, hh = cs[vlb], hold[vlb]
        o2 = np.lexsort((hh, hc))
        hc, hh = hc[o2], hh[o2]
        ucs, st0, cnt = np.unique(hc, return_index=True, return_counts=True)
        med = (hh[st0 + (cnt - 1) // 2] + hh[st0 + cnt // 2]) / 2.0          # per-wallet median buy->sell hold
        rt = np.bincount(hc[hh <= BOT_RT_S], minlength=W)[ucs]               # round trips within 60 s
        bot_w[ucs[(med < BOT_MEDIAN_HOLD_S) | (rt >= BOT_MIN_RT)]] = True
    bot_w &= n_tr_w >= BOT_MIN_TRADES
    prev = np.where(vlb, lb, np.where(vls, ls, -1))
    has = prev >= 0
    pi = np.maximum(prev, 0)
    big = np.maximum(tok_s, tok_s[pi]).astype(np.float64)
    wash_row = has & (ts_s - ts_s[pi] <= WASH_S) & (np.abs(tok_s - tok_s[pi]) < WASH_REL * big)
    wash_w = np.zeros(W, bool)
    wash_w[np.unique(cs[wash_row])] = True
    bot_w &= ~pooled_w
    wash_w &= ~pooled_w

    # ---- curve roles (venue 0)
    c_slot, c_ts, vsol0 = st["c_slot"], st["c_ts"], st["vsol0"]
    cb = (venue == 0) & buy & ~pool_t
    bundle_w = np.zeros(W, bool)
    bundle_w[np.unique(codes[cb & (slot == int(c_slot))])] = True
    cb_idx = np.flatnonzero(cb)
    sniper_w = np.zeros(W, bool)
    first_codes, first_pos = np.unique(codes[cb_idx], return_index=True)
    first_rows = cb_idx[first_pos]
    o = np.argsort(first_rows, kind="stable")
    first_codes, first_rows = first_codes[o], first_rows[o]
    sniper_w[first_codes[ts[first_rows] <= c_ts + SNIPER_WINDOW_S]] = True
    sniper_w[first_codes[:SNIPER_FIRST_N]] = True
    t20 = float(ts[first_rows[SNIPER_FIRST_N - 1]]) if len(first_rows) >= SNIPER_FIRST_N else float(g)
    roles_known = max(float(c_ts) + SNIPER_WINDOW_S, min(t20, float(g)))
    real_before = x0 / LAMPORTS - vsol0
    real_after = real_before + np.maximum(sol - fees, 0.0)
    band = np.clip(np.minimum(real_after, CURVE_BAND[1]) - np.maximum(real_before, CURVE_BAND[0]), 0.0, None)
    band = np.where(cb, band, 0.0)
    band_w = np.bincount(codes, weights=band, minlength=W)
    completer_code = int(np.argmax(band_w)) if W and band_w.max() > 0 else None
    completer_band = float(band_w[completer_code]) if completer_code is not None else None
    creator_code = None
    if st.get("creator"):
        try:
            ch = np.uint64(wallet_h(st["creator"]))
            k = int(np.searchsorted(uw, ch))
            if k < W and uw[k] == ch:
                creator_code = k
        except (ValueError, KeyError):
            creator_code = None

    # ---- AGENT (BOOST): pool buys in [g, g + 420 s) by wallets with no sell in the prefix
    pb = (venue == 1) & buy & (ts >= g) & (ts < g + C.AGENT_WINDOW_S) & ~pool_t
    sold = np.zeros(W, bool)
    sold[np.unique(codes[~buy])] = True
    cnt = np.bincount(codes[pb], minlength=W)
    cands = {}
    for c in np.flatnonzero((cnt >= C.flow_features.AGENT_MIN_BUYS) & ~sold):
        rows = np.flatnonzero(pb & (codes == c))
        cands[int(c)] = {"ts": ts[rows].tolist(), "sol": sol[rows].tolist(), "sells": 0}
    agent = C.flow_features.detect_agent(cands, int(g), rule="robust") if cands else None
    agent_code = int(agent["wallet"]) if agent else None
    agent_tok = float(tok[(codes == agent_code) & buy & (venue == 1)].sum() / TOK) if agent_code is not None else 0.0

    # ---- INSIDER set and its aggregates
    ins_w = bundle_w | sniper_w | transferee_w
    if creator_code is not None:
        ins_w[creator_code] = True
    if completer_code is not None:
        ins_w[completer_code] = True
    ins_w &= ~pooled_w
    if agent_code is not None:
        ins_w[agent_code] = False
    insider_hold = float(np.maximum(pos_w[ins_w], 0).sum() / TOK)
    ir = ins_w[codes]
    delta = (np.maximum(pos_after, 0) - np.maximum(pos_before, 0))[ir]
    insider_peak = float(max(np.cumsum(delta).max(), 0) / TOK) if delta.size else 0.0
    cost: dict[int, list] = {}
    for i in np.flatnonzero(ir):
        c = int(codes[i])
        s = cost.setdefault(c, [0, 0.0])   # [pos raw, cost SOL]
        if buy[i]:
            s[0] += int(tok[i])
            s[1] += float(sol[i])
        else:
            if s[0] > 0:
                s[1] *= 1.0 - min(int(tok[i]), s[0]) / s[0]
            s[0] -= int(tok[i])
            if s[0] <= 0:
                s[1] = 0.0
    ins_cost = float(sum(v[1] for v in cost.values() if v[0] > 0))
    ins_pp = float(sum(v[0] for v in cost.values() if v[0] > 0) / TOK)

    # ---- pool prices (SOL per whole token) on X = x + v, v carried along the chain
    pool = venue == 1
    vi = np.where(pool & (virt > 0), np.arange(n), -1)
    acc = np.maximum.accumulate(vi) if n else vi
    v_eff = np.where(acc >= 0, virt[np.maximum(acc, 0)], np.nan)
    with np.errstate(divide="ignore", invalid="ignore"):
        p_pre = np.where(pool, ((x0 + v_eff) / LAMPORTS) / (y0 / TOK), np.nan)
        y1 = np.where(buy, y0 - tok, y0 + tok)
        p_post = np.where(pool & (y1 > 0), p_pre * (y0 / y1) ** 2, np.nan)
    pr = np.flatnonzero(pool)
    y_last = float(y1[pr[-1]] / TOK) if len(pr) else None
    return _Prefix(n=n, ts=ts, venue=venue, buy=buy, sol=sol, tok=tok, codes=codes, uw=uw, pooled_w=pooled_w,
                   pos_before=pos_before, pos_after=pos_after, pos_w=pos_w, peak_w=peak_w, orphan=orphan,
                   transferee_w=transferee_w, bot_w=bot_w, wash_w=wash_w, agent=agent, agent_code=agent_code,
                   agent_tok=agent_tok, creator_code=creator_code, completer_code=completer_code,
                   completer_band_sol=completer_band, bundle_w=bundle_w, sniper_w=sniper_w,
                   roles_known_ts=roles_known, ins_w=ins_w, insider_hold=insider_hold, insider_peak=insider_peak,
                   insider_cost_sol=ins_cost, insider_pos_pos=ins_pp, p_pre=p_pre, p_post=p_post,
                   y_post_last=y_last, n_curve_buyers_seen=int(len(first_codes)))


class _LRU(OrderedDict):
    def __init__(self, cap: int) -> None:
        super().__init__()
        self.cap = cap

    def get_or(self, key, fn):
        if key in self:
            self.move_to_end(key)
            return self[key]
        v = fn()
        self[key] = v
        if len(self) > self.cap:
            self.popitem(last=False)
        return v


_PREFIX_CACHE = _LRU(64)
_FEAT_CACHE = _LRU(4096)


def clear_cache() -> None:
    _PREFIX_CACHE.clear()
    _FEAT_CACHE.clear()


def _fingerprint(tr: pd.DataFrame) -> tuple:
    if not len(tr):
        return (0,)
    return (len(tr), int(tr["ts"].to_numpy(np.int64).sum()), int(tr["tok"].to_numpy(np.int64).sum()),
            int(tr["wallet_h"].to_numpy(np.uint64).sum()), int(tr["usol"].to_numpy(np.int64).sum()),
            int(tr["ts"].iloc[-1]), int(tr["slot"].iloc[-1]))


# =========================================================================== features at tau (via AsOf only)

STATIC_FIELDS = ("curve_partial", "created_exact", "grad_delay_s", "c_slot", "c_ts", "creator", "vsol0",
                 "curve_top3_buy_sol", "curve_buy_sol", "curve_n_buyers", "pool_base0")


def _na(why: str, permanent: bool, **kw) -> dict:
    d = {"ok": False, "why": why, "permanent": permanent}
    d.update(kw)
    return d


def _static(snap: C.AsOf, tau: float) -> dict | str:
    out = {}
    for name in STATIC_FIELDS:
        lf = snap.legal_from(name)
        if lf is None:
            return f"no_legal_field:{name}"
        if tau < lf:
            return f"not_yet_known:{name}"
        out[name] = snap[name]
    return out


def s1_features(snap: C.AsOf, tau: float | None = None) -> dict:
    """S1 features (PREREG §4-§5) at ``tau`` (default ``snap.tau``; an earlier tau re-uses the snapshot's own
    trade prefix, so it can never see more than the snapshot). Every value is computed from B1 rows with
    ts <= tau and legal static fields. ``ok`` False => do not trade (``why`` says why, ``permanent`` => SKIP)."""
    tau = snap.tau if tau is None else min(float(tau), snap.tau)
    g = float(snap.g)
    tr = snap.trades
    if tr is None:
        return _na("no_b1", True)
    if tau < g:
        return _na("before_graduation", False)
    st = _static(snap, tau)
    if isinstance(st, str):
        return _na(st, False)
    if st["curve_partial"] or not st["created_exact"]:
        return _na("creation_not_scanned", True)
    if st["grad_delay_s"] is None or st["grad_delay_s"] <= FACTORY_DELAY_S:
        return _na("instant_or_unknown_grad_delay", True)
    if st["c_slot"] is None or st["c_ts"] is None or not st["creator"] or st["vsol0"] is None:
        return _na("creation_fields_null", True)
    if tau >= g + B1_HORIZON_S:
        return _na("beyond_b1_horizon", True)
    ts_all = tr["ts"].to_numpy(np.int64)
    n = int(np.searchsorted(ts_all, tau, side="right"))
    pre = tr.iloc[:n]
    if n and (pre["ts"].to_numpy(np.int64) > tau).any():          # defence in depth (non-monotone block times)
        pre = pre[pre["ts"].to_numpy(np.int64) <= tau]
    if B1_MAX_TRADES is not None and len(pre) >= B1_MAX_TRADES:
        return _na("b1_truncated", True)
    if not len(pre):
        return _na("no_trades_before_tau", False)
    skey = (snap.mint, g) + tuple(st[k] for k in STATIC_FIELDS)
    fp = (skey, _fingerprint(pre))
    key = (fp, float(tau))
    if key in _FEAT_CACHE:
        _FEAT_CACHE.move_to_end(key)
        return _FEAT_CACHE[key]
    P = _PREFIX_CACHE.get_or(fp, lambda: _build_prefix(pre, st, g))
    if tau < P.roles_known_ts:
        return _na("roles_not_yet_knowable", False)
    out = _tau_features(P, st, g, tau)
    if tau >= g + G1_AT_S:
        n120 = int(np.searchsorted(pre["ts"].to_numpy(np.int64), g + G1_AT_S, side="right"))
        pre120 = pre.iloc[:n120]
        fp120 = (skey, _fingerprint(pre120))
        P120 = _PREFIX_CACHE.get_or(fp120, lambda: _build_prefix(pre120, st, g))
        out.update(_g1(P120, st, g))
    else:
        out.update({"g1_class": None})
    out["ok"] = out.get("g1_class") is not None
    out["why"] = "" if out["ok"] else "g1_class_null"
    out["permanent"] = not out["ok"] and tau >= g + G1_AT_S
    _FEAT_CACHE[key] = out
    if len(_FEAT_CACHE) > _FEAT_CACHE.cap:
        _FEAT_CACHE.popitem(last=False)
    return out


def _mech(P: _Prefix, tau: float, excl: np.ndarray) -> np.ndarray:
    """MECH wallets at tau (PLAN §4.5) over pool trades in (tau - 30 min, tau]."""
    W = len(P.uw)
    mech = np.zeros(W, bool)
    win = (P.venue == 1) & (P.ts > tau - MECH_WINDOW_S) & (P.ts <= tau)
    wb = win & P.buy
    cnt = np.bincount(P.codes[wb], minlength=W)
    cand = np.flatnonzero((cnt >= MECH_MIN_BUYS) & ~excl)
    if not len(cand):
        return mech
    pool_rows = np.flatnonzero(P.venue == 1)
    pts, ppost = P.ts[pool_rows], P.p_post[pool_rows]
    for c in cand:
        rows = np.flatnonzero(wb & (P.codes == c))
        bsol = P.sol[rows]
        ssol = P.sol[win & ~P.buy & (P.codes == c)].sum()
        if ssol > MECH_MAX_SELL_FRAC * bsol.sum():
            continue
        gaps = np.diff(P.ts[rows]).astype(float)
        if not len(gaps) or gaps.mean() <= 0 or gaps.std() / gaps.mean() >= MECH_GAP_CV:
            continue
        if bsol.mean() <= 0 or bsol.std() / bsol.mean() >= MECH_SIZE_CV:
            continue
        k = np.searchsorted(pts, P.ts[rows] - 60, side="right") - 1
        p_then = np.where(k >= 0, ppost[np.maximum(k, 0)], np.nan)
        r1 = P.p_pre[rows] / p_then - 1.0
        ok = np.isfinite(r1)
        rho = _spearman(bsol[ok], r1[ok])
        if abs(rho) >= MECH_SPEARMAN:
            continue
        mech[c] = True
    return mech


def _spearman(a: np.ndarray, b: np.ndarray) -> float:
    if len(a) < 3:
        return 0.0
    ra, rb = pd.Series(a).rank().to_numpy(), pd.Series(b).rank().to_numpy()
    if ra.std() == 0 or rb.std() == 0:
        return 0.0
    return float(np.corrcoef(ra, rb)[0, 1])


def _tau_features(P: _Prefix, st: dict, g: float, tau: float) -> dict:
    W = len(P.uw)
    agent_w = np.zeros(W, bool)
    if P.agent_code is not None:
        agent_w[P.agent_code] = True
    excl_mech = P.pooled_w | agent_w
    if P.creator_code is not None:
        excl_mech = excl_mech.copy()
        excl_mech[P.creator_code] = True
    mech_w = _mech(P, tau, excl_mech)
    org_w = ~(P.pooled_w | P.ins_w | agent_w | P.bot_w | P.wash_w | mech_w)
    pool = P.venue == 1
    orgt, inst, agt = org_w[P.codes], P.ins_w[P.codes], agent_w[P.codes]

    def win(lo, hi, lo_incl=False):
        m = pool & (P.ts <= hi)
        return m & ((P.ts >= lo) if lo_incl else (P.ts > lo))

    w10, w5 = win(tau - 600, tau), win(tau - 300, tau)
    b_org10 = float(P.sol[w10 & P.buy & orgt].sum())
    s_org10 = float(P.sol[w10 & ~P.buy & orgt].sum())
    b_org5 = float(P.sol[w5 & P.buy & orgt].sum())
    s_org5 = float(P.sol[w5 & ~P.buy & orgt].sum())
    org_buyers10 = int(len(np.unique(P.codes[w10 & P.buy & orgt])))
    sells10 = w10 & ~P.buy & ~P.pooled_w[P.codes]
    st_tok = float(P.tok[sells10].sum())
    orphan10 = float(P.orphan[sells10].sum()) / st_tok if st_tok > 0 else 0.0
    if tau >= g + BOOST_WINDOW_S:
        wb = win(g, g + BOOST_WINDOW_S, lo_incl=True)
        boost_absorb = float(P.sol[wb & P.buy & orgt].sum() - P.sol[wb & ~P.buy & orgt].sum())
        b_agent = float(P.sol[wb & P.buy & agt].sum())
        into_boost = float(P.sol[wb & ~P.buy & inst].sum()) / max(b_agent, 0.1)
    else:
        boost_absorb = into_boost = b_agent = None
    # creator (all venues)
    cc = P.creator_code
    if cc is None:
        cr_peak = cr_sold_cum = cr_sold10 = 0.0
    else:
        mine = P.codes == cc
        cr_peak = float(P.peak_w[cc] / TOK)
        cr_sold_cum = float(P.tok[mine & ~P.buy].sum() / TOK)
        cr_sold10 = float(P.tok[mine & ~P.buy & (P.ts > tau - 600)].sum() / TOK)

    def frac(x):
        if cr_peak > 0:
            return x / cr_peak
        return 0.0 if x == 0 else math.inf

    comp = P.completer_code
    comp_frac = None
    if comp is not None:
        pk = P.peak_w[comp]
        comp_frac = float(max(P.pos_w[comp], 0) / pk) if pk > 0 else 0.0
    pool_rows = np.flatnonzero(pool)
    p_now = float(P.p_post[pool_rows[-1]]) if len(pool_rows) else None
    y_now = P.y_post_last if P.y_post_last is not None else (st.get("pool_base0") or None)
    circ = (SUPPLY - y_now - P.agent_tok) if y_now is not None else None
    avg_cost = P.insider_cost_sol / P.insider_pos_pos if P.insider_pos_pos > 0 else None
    return {
        "tau": float(tau), "n_trades": int(P.n),
        "insider_rem": (P.insider_hold / P.insider_peak) if P.insider_peak > 0 else None,
        "insider_hold": P.insider_hold, "insider_peak": P.insider_peak,
        "overhang": (P.insider_hold / circ) if circ and circ > 0 else None,
        "insider_mult": (p_now / avg_cost) if (p_now and avg_cost) else None,
        "boost_absorb": boost_absorb, "insider_into_boost": into_boost, "agent_buy_sol_5m": b_agent,
        "org_net10": b_org10 - s_org10, "org_buyers10": org_buyers10, "org_net5": b_org5 - s_org5,
        "orphan_share10": orphan10,
        "creator_peak": cr_peak, "creator_sold_cum": cr_sold_cum,
        "creator_sold_frac": frac(cr_sold_cum), "creator_sold10": frac(cr_sold10),
        "completer_pos_frac": comp_frac,
        "agent_detected": P.agent is not None, "agent_known_at": P.agent["known_at"] if P.agent else None,
        "agent_slices": P.agent["n_slices"] if P.agent else 0,
        "n_wallets": int(W), "n_insiders": int(P.ins_w.sum()), "n_bundle": int(P.bundle_w.sum()),
        "n_snipers": int(P.sniper_w.sum()), "n_transferees": int(P.transferee_w.sum()),
        "n_bot": int(P.bot_w.sum()), "n_wash": int(P.wash_w.sum()), "n_mech": int(mech_w.sum()),
        "n_organic": int(org_w.sum()), "creator_traded": cc is not None,
    }


def _g1(P: _Prefix, st: dict, g: float) -> dict:
    """G1 'G-chain' class at g + 120 s (PREREG §5) from the trade prefix with ts <= g + 120."""
    pool_b = (P.venue == 1) & P.buy & (P.ts >= g) & (P.ts <= g + G1_AT_S)
    ag = P.codes == P.agent_code if P.agent_code is not None else np.zeros(P.n, bool)
    b_all = float(P.sol[pool_b].sum())
    amm_buy = b_all - float(P.sol[pool_b & ag].sum())
    real = pool_b & ~ag & ~P.pooled_w[P.codes]
    per = np.bincount(P.codes[real], weights=P.sol[real], minlength=len(P.uw))
    buyers = int((per > 0).sum())
    top5 = float(np.sort(per)[::-1][:5].sum()) / amm_buy if amm_buy > 0 else None
    comp_share = P.completer_band_sol / 30.0 if P.completer_band_sol is not None else None
    top3 = (st["curve_top3_buy_sol"] / st["curve_buy_sol"]
            if st["curve_top3_buy_sol"] is not None and st["curve_buy_sol"] else None)
    ncb = st["curve_n_buyers"]
    gd = st["grad_delay_s"]
    cls = None
    if amm_buy >= OPERATOR_BUY_SOL and buyers <= OPERATOR_MAX_BUYERS:
        cls = "OPERATOR"
    elif gd is not None and gd <= FACTORY_DELAY_S and top5 is not None and top5 >= FACTORY_TOP5:
        cls = "FACTORY"
    elif gd is not None and gd > FACTORY_DELAY_S:
        conds = [comp_share is not None and comp_share >= COMPLETED_SHARE,
                 top3 is not None and top3 >= COMPLETED_TOP3,
                 ncb is not None and ncb < COMPLETED_MIN_BUYERS]
        if any(conds):
            cls = "COMPLETED"
        elif comp_share is not None and top3 is not None and ncb is not None:
            cls = "ORGANIC"          # every input known and no rule fired (NULL inputs never default to ORGANIC)
    return {"g1_class": cls, "amm_buy_sol_2m": amm_buy, "amm_buyers_2m": buyers, "amm_top5_share_2m": top5,
            "completer_share": comp_share, "curve_top3_share": top3, "n_curve_buyers": ncb}


# =========================================================================== strategies


def checkpoint_at(snap: C.AsOf, checkpoints_min) -> int | None:
    """The checkpoint c whose rounded-down grid time is ``snap.t`` (t <= g + c min < t + 60), else None."""
    for c in checkpoints_min:
        target = snap.g + 60.0 * c
        if snap.t <= target < snap.t + 60.0:
            return int(c)
    return None


def _past_last(snap: C.AsOf, checkpoints_min) -> bool:
    return snap.t > snap.g + 60.0 * max(checkpoints_min)


def nonflow_ok(snap: C.AsOf, f: dict | None = None) -> bool:
    """Non-flow eligibility (control 1, control 2 = placebo_eligible): features computable, class allowed, alive."""
    f = f if f is not None else s1_features(snap)
    return bool(f["ok"] and f["g1_class"] in ALLOWED_CLASSES and snap.alive())


def placebo_eligible(snap: C.AsOf) -> bool:
    return nonflow_ok(snap)


def _flow_entry_ok(f: dict, p: Mapping) -> bool:
    def le(v, x):
        return v is not None and v <= x

    def lt(v, x):
        return v is not None and v < x

    def gt(v, x):
        return v is not None and v > x

    if f["g1_class"] == "COMPLETED" and not le(f["completer_pos_frac"], p["completer_rem_max"]):
        return False
    return (le(f["insider_rem"], p["theta_rem"]) and gt(f["org_net10"], 0.0)
            and f["org_buyers10"] is not None and f["org_buyers10"] >= p["theta_buy"]
            and lt(f["orphan_share10"], p["orphan10_max"]) and lt(f["creator_sold10"], p["creator10_max"])
            and (not p["absorb_req"] or gt(f["boost_absorb"], 0.0)))


def _exit_spec(p: Mapping) -> C.ExitSpec:
    return C.ExitSpec(trail_pct=p["trail_pct"], max_hold_s=p["max_hold_s"])


def flow_exit(snap: C.AsOf, p: Mapping, pos: C.PositionView):
    """Flow exits (PREREG §8). The entry baseline is recomputed at tau_entry from this snapshot's own trade prefix,
    so signals and placebos (empty state) are treated identically. Beyond B1: mechanical exits only."""
    f = s1_features(snap)
    if not f["ok"]:
        return None
    f0 = s1_features(snap, tau=pos.t_dec - C.DECISION_LAG_S)
    if f["org_net5"] <= p["exit_org_net5"]:
        return C.Exit("org_net5")
    if f["orphan_share10"] > p["exit_orphan10"]:
        return C.Exit("orphan10")
    base_ok = f0.get("creator_sold_cum") is not None and "insider_hold" in f0
    if base_ok and f["creator_peak"] > 0 and \
            (f["creator_sold_cum"] - f0["creator_sold_cum"]) / f["creator_peak"] >= p["exit_creator_after"]:
        return C.Exit("creator_sells")
    if base_ok and f["insider_hold"] - f0["insider_hold"] > p["exit_insider_grow"] * SUPPLY:
        return C.Exit("insider_grow")
    return None


def s1_strategy(snap: C.AsOf, p: Mapping, pos: C.PositionView | None):
    """The S1 entry rule (PREREG §8). Returns Enter / SKIP / None; in a position, flow exits."""
    if pos is not None:
        return flow_exit(snap, p, pos)
    cps = p["checkpoints_min"]
    if _past_last(snap, cps):
        return C.SKIP
    cp = checkpoint_at(snap, cps)
    if cp is None:
        return None
    f = s1_features(snap)
    if not f["ok"]:
        return C.SKIP if f["permanent"] else None
    if f["g1_class"] not in ALLOWED_CLASSES:
        return C.SKIP
    if not snap.alive() or not _flow_entry_ok(f, p):
        return None
    return C.Enter(exits=_exit_spec(p), tag=f"cp{cp}",
                   state={"cp": cp, "insider_rem": f["insider_rem"], "org_net10": f["org_net10"],
                          "org_buyers10": f["org_buyers10"], "boost_absorb": f["boost_absorb"]})


def control1_strategy(snap: C.AsOf, p: Mapping, pos: C.PositionView | None):
    """Control 1: same checkpoints, universe, class filter and exits; NO flow conditions (PREREG §9)."""
    if pos is not None:
        return flow_exit(snap, p, pos)
    cps = p["checkpoints_min"]
    if _past_last(snap, cps):
        return C.SKIP
    cp = checkpoint_at(snap, cps)
    if cp is None:
        return None
    f = s1_features(snap)
    if not f["ok"]:
        return C.SKIP if f["permanent"] else None
    if f["g1_class"] not in ALLOWED_CLASSES:
        return C.SKIP
    if not snap.alive():
        return None
    return C.Enter(exits=_exit_spec(p), tag=f"cp{cp}")


def gate_strategy(snap: C.AsOf, p: Mapping, pos: C.PositionView | None):
    """Dose-response gate (PREREG §7): enter every eligible coin at the checkpoint, hold 30 min, tag insider_rem."""
    if pos is not None:
        return None
    cp = p["checkpoint_min"]
    if _past_last(snap, (cp,)):
        return C.SKIP
    if checkpoint_at(snap, (cp,)) is None:
        return None
    f = s1_features(snap)
    if not nonflow_ok(snap, f) or f["insider_rem"] is None:
        return C.SKIP
    return C.Enter(exits=C.ExitSpec(max_hold_s=p["hold_s"]), tag=f"rem={f['insider_rem']:.9f}")


# =========================================================================== params (every distinct dict = one trial)

BASE_PARAMS = {
    "version": VERSION, "checkpoints_min": list(CHECKPOINTS_MIN), "classes": list(ALLOWED_CLASSES),
    "orphan10_max": 0.15, "creator10_max": 0.20, "completer_rem_max": 0.10,
    "trail_pct": 0.30, "max_hold_s": 5400, "exit_org_net5": -1.0, "exit_orphan10": 0.25,
    "exit_creator_after": 0.20, "exit_insider_grow": 0.02,
}


def grid_params() -> list[dict]:
    """The pre-registered TRAIN grid: exactly 8 configurations (PLAN §4.3 / §3.4 limit 8)."""
    return [{**BASE_PARAMS, "theta_rem": r, "theta_buy": b, "absorb_req": a}
            for r in THETA_REM for b in THETA_BUY for a in ABSORB_REQ]


def gate_params(cp: int) -> dict:
    return {"version": VERSION, "gate": "dose_response", "checkpoint_min": int(cp), "hold_s": GATE_HOLD_S,
            "classes": list(ALLOWED_CLASSES)}


def control_params() -> dict:
    p = {k: v for k, v in BASE_PARAMS.items() if k not in ("orphan10_max", "creator10_max", "completer_rem_max")}
    p["control"] = "nonflow_population"
    return p


def config_label(p: Mapping) -> str:
    return f"rem{p['theta_rem']:.2f}_buy{p['theta_buy']}_abs{'Y' if p['absorb_req'] else 'N'}"


# =========================================================================== control 1 (orchestration: not feature code)


def checkpoint_time(cd: C.CoinData, cp: int) -> float:
    """The decision-grid time t (minute boundary + 20 s) with t <= g + cp min < t + 60 (see :func:`checkpoint_at`)."""
    return float(cd.m0 + C.GRID_OFFSET_S + 60 * math.floor((cd.g + 60.0 * cp - cd.m0 - C.GRID_OFFSET_S) / 60.0))


def control1_entries(ds: C.Dataset, p: Mapping) -> list[tuple[str, float, C.Enter]]:
    """Control 1 (PLAN 4.3: "the same coins at the same t without the flow conditions"): EVERY coin that is
    non-flow eligible (features computable, class allowed, alive) at checkpoint cp is entered at cp, for every cp.
    S1 trades at cp are then compared with control trades at the same cp (:func:`matched_control_diff`), so the
    entry age (g + 6 min sits right after the BOOST cliff) cannot drive the difference."""
    out = []
    for m in ds.mints:
        cd = ds.coin(m)
        for cp in p["checkpoints_min"]:
            t = checkpoint_time(cd, int(cp))
            if nonflow_ok(ds.asof(m, t)):
                out.append((m, t, C.Enter(exits=_exit_spec(p), tag=f"cp{int(cp)}")))
    return out



# =========================================================================== statistics helpers


def _clean_json(o: Any) -> Any:
    if isinstance(o, dict):
        return {str(k): _clean_json(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean_json(v) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating, float)):
        f = float(o)
        if math.isnan(f):
            return None
        if math.isinf(f):
            return "inf" if f > 0 else "-inf"
        return f
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, Path):
        return str(o)
    return o


def diff_ci(a: pd.DataFrame, b: pd.DataFrame, B: int = 10_000, seed: int = 0) -> dict:
    """mean(a) - mean(b) with a 95 % CI from independent coin bootstraps of both sets."""
    if not len(a) or not len(b):
        return {"diff": None, "ci95": None, "n_a": int(len(a)), "n_b": int(len(b))}
    ma = C.coin_bootstrap_means(a["ret_net"].to_numpy(float), a["mint"].to_numpy(object), B, seed)
    mb = C.coin_bootstrap_means(b["ret_net"].to_numpy(float), b["mint"].to_numpy(object), B, seed + 1)
    d = float(a["ret_net"].mean() - b["ret_net"].mean())
    lo, hi = np.quantile(ma - mb, [0.025, 0.975])
    return {"diff": d, "ci95": [float(lo), float(hi)], "n_a": int(len(a)), "n_b": int(len(b))}


def matched_control_diff(sig: pd.DataFrame, ctrl: pd.DataFrame, B: int = 10_000, seed: int = 0) -> dict:
    """S1 minus control 1 at the SAME checkpoints: mean(S1) - sum_cp w_cp mean(control at cp), w_cp = S1's share of
    trades at cp (tags ``cp<N>``). 95 % / 90 % CIs from a JOINT coin bootstrap (a coin in both sets carries its
    trades in both, as in d1.diff_ci). ``diff`` is None when some S1 checkpoint has no control trade."""
    out: dict[str, Any] = {"diff": None, "ci95": None, "ci90": None, "n_sig": int(len(sig)), "n_ctrl": int(len(ctrl)),
                           "weights": {}, "ctrl_weighted_mean": None, "unmatched_cps": []}
    if not len(sig) or not len(ctrl):
        return out
    w = sig["tag"].value_counts(normalize=True).sort_index()
    out["weights"] = {str(k): float(v) for k, v in w.items()}
    have = set(ctrl["tag"])
    miss = [str(k) for k in w.index if k not in have]
    if miss:
        out["unmatched_cps"] = miss
        return out
    cm = ctrl.groupby("tag")["ret_net"].mean()
    out["ctrl_weighted_mean"] = float(sum(w[k] * cm[k] for k in w.index))
    out["diff"] = float(sig["ret_net"].mean() - out["ctrl_weighted_mean"])
    coins = pd.Index(pd.unique(pd.concat([sig["mint"], ctrl["mint"]], ignore_index=True)))
    nc = len(coins)
    i_s = coins.get_indexer(sig["mint"])
    ss, ns = np.bincount(i_s, sig["ret_net"].to_numpy(float), nc), np.bincount(i_s, minlength=nc).astype(float)
    per_cp = []
    for k in w.index:
        sub = ctrl[ctrl["tag"] == k]
        ic = coins.get_indexer(sub["mint"])
        per_cp.append((float(w[k]), np.bincount(ic, sub["ret_net"].to_numpy(float), nc),
                       np.bincount(ic, minlength=nc).astype(float)))
    rng = np.random.default_rng(seed)
    diffs = []
    step = max(1, int(2_000_000 // max(nc, 1)))
    for s0 in range(0, B, step):
        m = min(step, B - s0)
        idx = rng.integers(0, nc, size=(m, nc))
        W = np.zeros((m, nc))
        np.add.at(W, (np.repeat(np.arange(m), nc), idx.ravel()), 1.0)
        den = W @ ns
        ok = den > 0
        val = np.where(ok, (W @ ss) / np.where(ok, den, 1.0), np.nan)
        for wk, sc, nc_k in per_cp:
            d_k = W @ nc_k
            ok &= d_k > 0
            val = val - wk * np.where(d_k > 0, (W @ sc) / np.where(d_k > 0, d_k, 1.0), np.nan)
        diffs.append(val[ok])
    d = np.concatenate(diffs) if diffs else np.zeros(0)
    if len(d) >= 100:
        out["ci95"] = [float(np.quantile(d, 0.025)), float(np.quantile(d, 0.975))]
        out["ci90"] = [float(np.quantile(d, 0.05)), float(np.quantile(d, 0.95))]
    return out


def gate_quintiles(trades: pd.DataFrame, reveal: bool = True, B: int = 10_000) -> dict:
    """Quintiles of insider_rem (ascending; ties by decision time then mint), per-quintile mean net return,
    adjacent inversions (mean(Q_{i+1}) > mean(Q_i)), Q1 - Q5 with a coin-bootstrap CI."""
    n = int(len(trades))
    out: dict[str, Any] = {"n": n}
    if n == 0:
        out.update({"quintiles": [], "inversions": None, "q1_minus_q5": None})
        return out
    t = trades.assign(rem=trades["tag"].str.slice(4).astype(float))
    t = t.sort_values(["rem", "t_dec", "mint"], kind="stable").reset_index(drop=True)
    t["q"] = (np.arange(n) * 5 // n) + 1
    qs = []
    for q in range(1, 6):
        s = t[t["q"] == q]
        qs.append({"q": q, "n": int(len(s)), "rem_min": float(s["rem"].min()) if len(s) else None,
                   "rem_max": float(s["rem"].max()) if len(s) else None,
                   "mean": float(s["ret_net"].mean()) if len(s) else None,
                   "median": float(s["ret_net"].median()) if len(s) else None})
    means = [q["mean"] for q in qs]
    inv = sum(1 for i in range(4) if means[i] is not None and means[i + 1] is not None and means[i + 1] > means[i])
    spread = diff_ci(t[t["q"] == 1], t[t["q"] == 5], B=B)
    out.update({"quintiles": qs, "inversions": int(inv), "q1_minus_q5": spread["diff"], "q1_minus_q5_ci95": spread["ci95"],
                "n_ties_at_mode": int(t["rem"].round(9).value_counts().iloc[0]),
                "n_distinct_rem": int(t["rem"].round(9).nunique())})
    if not reveal:
        for q in out["quintiles"]:
            q["mean"] = q["median"] = "hidden"
        out["q1_minus_q5"] = out["q1_minus_q5_ci95"] = out["inversions"] = "hidden"
    return out


def gate_verdict_train(stats: dict[int, dict]) -> dict:
    """PREREG §7 TRAIN: per checkpoint >= 100 coins, <= 1 adjacent inversion, mean(Q1) > mean(Q5)."""
    per, status = {}, "PASS"
    for cp, s in stats.items():
        if s["n"] < GATE_MIN_COINS["train"]:
            per[cp] = "UNDERPOWERED"
            continue
        ok = s["inversions"] <= 1 and s["q1_minus_q5"] is not None and s["q1_minus_q5"] > 0
        per[cp] = "PASS" if ok else "FAIL"
    if any(v == "FAIL" for v in per.values()):
        status = "GATE_FAIL"
    elif any(v == "UNDERPOWERED" for v in per.values()):
        status = "GATE_UNDERPOWERED"
    return {"status": status, "per_checkpoint": per}


def gate_verdict_val(stats: dict[int, dict]) -> dict:
    """PREREG §7 VAL: per checkpoint >= 50 coins and mean(Q1) - mean(Q5) >= 0.05."""
    per, status = {}, "PASS"
    for cp, s in stats.items():
        if s["n"] < GATE_MIN_COINS["val"]:
            per[cp] = "UNDERPOWERED"
        else:
            per[cp] = "PASS" if (s["q1_minus_q5"] is not None and s["q1_minus_q5"] >= GATE_VAL_MIN_SPREAD) else "FAIL"
    if any(v == "FAIL" for v in per.values()):
        status = "GATE_VAL_FAIL"
    elif any(v == "UNDERPOWERED" for v in per.values()):
        status = "GATE_VAL_UNDERPOWERED"
    return {"status": status, "per_checkpoint": per}


def shortlist_rule(rows: list[dict]) -> dict:
    """PREREG §11 TRAIN shortlist. ``rows``: per config {params, n, n_coins, mean, mean_without_top2, ci90,
    control1_diff, placebo_diff}. -> {status, shortlist (<= 2 params), ranked}."""
    qual, powered = [], False
    for r in rows:
        if r["n"] >= SHORTLIST_MIN_TRADES and r["n_coins"] >= SHORTLIST_MIN_COINS:
            powered = True
        else:
            continue
        if (r["mean"] is not None and r["mean"] > 0 and r["mean_without_top2"] is not None
                and r["mean_without_top2"] > 0 and r["control1_diff"] is not None
                and r["control1_diff"] >= CONTROL_MARGIN and r["placebo_diff"] is not None and r["placebo_diff"] > 0
                and r["ci90"]):
            qual.append(r)
    qual.sort(key=lambda r: (-r["ci90"][0], -r["mean"], C.params_hash(r["params"])))
    if qual:
        return {"status": "SHORTLISTED", "shortlist": [r["params"] for r in qual[:2]],
                "ranked": [config_label(r["params"]) for r in qual]}
    return {"status": "NO_CONFIG" if powered else "UNDERPOWERED_TRAIN", "shortlist": [], "ranked": []}


def val_selection(rows: list[dict]) -> dict:
    """PREREG §11 VAL -> TEST selection. rows: per shortlisted config {params, n, mean, ci90, control1_diff}."""
    qual = [r for r in rows if r["n"] >= VAL_MIN_TRADES and r["mean"] is not None and r["mean"] > 0
            and r["control1_diff"] is not None and r["control1_diff"] >= CONTROL_MARGIN and r["ci90"]]
    qual.sort(key=lambda r: (-r["ci90"][0], -r["mean"]))
    if qual:
        return {"status": "SELECTED", "selected": qual[0]["params"]}
    if all(r["n"] < VAL_MIN_TRADES for r in rows):
        return {"status": "UNDERPOWERED_VAL", "selected": None}
    return {"status": "FAIL_VAL", "selected": None}


# =========================================================================== data coverage (counts only)


def _read_flow():
    f = C.flow_dir()
    return tuple(C._read_parquet(f / n) for n in ("graduates.parquet", "b2_coins.parquet", "b2_bars.parquet"))


def b1_mints() -> set[str]:
    p = C.flow_dir() / "b1_trades.parquet"
    if not p.exists():
        return set()
    return set(pd.read_parquet(p, columns=["mint"])["mint"].unique())


def universe_mask(coins: pd.DataFrame) -> pd.Series:
    """S1-universe among common.py usable coins (PREREG §3), from graduation-time columns (counts only)."""
    gd = pd.to_numeric(coins["grad_delay_s"], errors="coerce")
    return (~coins["curve_partial"].astype(bool)) & coins["created_exact"].astype(bool) & (gd > FACTORY_DELAY_S)


def coverage_counts(split: str) -> dict:
    """Counts only (no prices, no returns): split coverage from common.py plus B1 coverage of the S1-universe."""
    ds = C.coverage_dataset(split)
    uni = ds.coins[universe_mask(ds.coins)] if len(ds.coins) else ds.coins
    have = b1_mints()
    n_uni = int(len(uni))
    n_b1 = int(uni["mint"].isin(have).sum()) if n_uni else 0
    cov = ds.coverage
    complete = bool(cov.get("complete")) and cov.get("chain_hours_scanned_frac", 0) >= 0.999
    return {"split": split, "usable": int(len(ds.coins)), "s1_universe": n_uni, "b1_covered": n_b1,
            "b1_frac": (n_b1 / n_uni) if n_uni else 0.0, "split_complete": complete,
            "chain_hours_scanned_frac": cov.get("chain_hours_scanned_frac"),
            "days_full": cov.get("days_full"), "days_expected": cov.get("days_expected"),
            "b1_file": (C.flow_dir() / "b1_trades.parquet").exists(), "problems": C.coverage_problems(cov),
            "problems_provisional": C.coverage_problems(cov, provisional=True)}


def check_data(split: str, allow_partial: bool = False) -> dict:
    cc = coverage_counts(split)
    problems = []
    if not cc["b1_file"]:
        problems.append("b1_trades.parquet does not exist (backfill phase P4b has not run: research/flow/run_b1.sh)")
    if cc["s1_universe"] == 0:
        problems.append(f"no S1-universe coins in split {split!r} yet")
    elif cc["b1_frac"] < B1_MIN_COVERAGE:
        problems.append(f"B1 covers {cc['b1_covered']}/{cc['s1_universe']} S1-universe coins "
                        f"({cc['b1_frac']:.1%} < {B1_MIN_COVERAGE:.0%})")
    if not cc["split_complete"] and not allow_partial:
        problems.append(f"split {split!r} coverage incomplete (hours scanned {cc['chain_hours_scanned_frac']}, "
                        f"full days {cc['days_full']}/{cc['days_expected']})")
    # common.coverage_problems: mid-run hours and missing B2 (waived for a provisional TRAIN), SOL/USD lookahead (never)
    problems += cc.get("problems_provisional" if allow_partial else "problems") or []
    gok, gbad = C.validation_gates(split)
    if not gok:
        problems.append("PLAN 8 stop rule 1 (data first): " + "; ".join(gbad))
    cc["problems"] = problems
    return cc


# =========================================================================== stage machinery

STAGES = ("status", "debug", "train", "val", "test", "confirm", "final")


def _prereg_sha() -> str | None:
    p = s1_dir() / "PREREG.md"
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None


def _lock_path() -> Path:
    return s1_dir() / "prereg.lock"


def _read_json(name: str) -> dict | None:
    p = s1_dir() / name
    return json.loads(p.read_text()) if p.exists() else None


def _ledger_runs(hyp: str, split: str) -> int:
    with C._ledger(None, write=False) as led:
        return sum(1 for r in led["runs"] if r["hypothesis"] == hyp and r["split"] == split and not r.get("debug"))


def _require_prereg_frozen() -> None:
    sha = _prereg_sha()
    lk = _lock_path()
    if sha is None:
        raise StageRefused("S1/PREREG.md is missing")
    if not lk.exists():
        raise StageRefused("no official TRAIN run yet (S1/prereg.lock missing): run --stage train first")
    if json.loads(lk.read_text())["sha256"] != sha:
        raise StageRefused("S1/PREREG.md changed after the first official TRAIN run: that is a new version")


def _env(flag: str) -> None:
    if os.environ.get(flag) != "1":
        raise StageRefused(f"needs env {flag}=1 (set by whoever runs the judge; s1.py never sets it)")


def prerequisites(stage: str, allow_partial: bool = False) -> None:
    """Raise StageRefused when ``stage`` may not run now (PREREG §11). Data checks are separate (check_data)."""
    if stage in ("status", "debug"):
        return
    if stage == "train":
        if _prereg_sha() is None:
            raise StageRefused("write S1/PREREG.md before any TRAIN run")
        if _read_json("val.json") is not None or _ledger_runs(HYP, "val") or _ledger_runs(HYP_GATE, "val"):
            raise StageRefused("S1 already ran on VAL: TRAIN is closed (re-running it could change the shortlist)")
        lk = _lock_path()
        if lk.exists() and json.loads(lk.read_text())["sha256"] != _prereg_sha() and not allow_partial:
            raise StageRefused("S1/PREREG.md changed after the first official TRAIN run: that is a new version")
        return
    _require_prereg_frozen()
    if stage == "val":
        tr = _read_json("train.json")
        if tr is None or tr.get("status") != "SHORTLISTED":
            raise StageRefused(f"VAL needs an official TRAIN run with status SHORTLISTED (have "
                               f"{None if tr is None else tr.get('status')})")
        for h in (HYP, HYP_GATE, HYP_CTRL):
            if not (C.shortlist_dir() / f"{h}.json").exists():
                raise StageRefused(f"no written VAL shortlist for {h} (shortlists/{h}.json)")
        if _read_json("val.json") is not None:
            raise StageRefused("VAL already ran for S1 (S1/val.json exists)")
        return
    if stage == "test":
        v = _read_json("val.json")
        if v is None or v.get("status") != "SELECTED":
            raise StageRefused(f"TEST needs VAL status SELECTED (have {None if v is None else v.get('status')})")
        if _read_json("test.json") is not None or _ledger_runs(HYP, "test") or _ledger_runs(HYP_CTRL, "test"):
            raise StageRefused("S1 already had its one TEST run")
        _env("LAB2_ALLOW_TEST")
        return
    if stage == "confirm":
        t = _read_json("test.json")
        if t is None:
            raise StageRefused("CONFIRM needs the TEST run first")
        if not t.get("confirm_allowed"):
            raise StageRefused(f"TEST did not qualify S1 for CONFIRM ({t.get('confirm_reason')}): S1 has failed")
        if _read_json("confirm.json") is not None or _ledger_runs(HYP, "confirm") or _ledger_runs(HYP_CTRL, "confirm"):
            raise StageRefused("S1 already had its one CONFIRM run")
        _env("LAB2_ALLOW_CONFIRM")
        return
    if stage == "final":
        if _read_json("test.json") is None or not _ledger_runs(HYP, "test"):
            raise StageRefused("never FINAL before TEST")
        if _read_json("final.json") is not None or _ledger_runs(HYP, "final"):
            raise StageRefused("S1 already had its one FINAL run")
        _env("LAB2_ALLOW_FINAL")
        return
    raise ValueError(stage)


# loaders are module-level so tests can substitute small datasets
def load_split(split: str) -> C.Dataset:
    return C.load(split, _internal=(split == "val"))


class _Store:
    """Writes raw run outputs immediately (one-shot splits must never lose a run to a later crash)."""

    def __init__(self, stage: str) -> None:
        self.stage = stage
        self.trades: list[pd.DataFrame] = []
        self.placebo: list[pd.DataFrame] = []
        self.stress: list[pd.DataFrame] = []

    def add(self, run: str, res: C.Result) -> None:
        self.trades.append(res.trades.assign(run=run))
        if len(res.placebo):
            self.placebo.append(res.placebo.assign(run=run))
        for k, v in res.stress.items():
            self.stress.append(v.assign(run=run, stress=k))
        self.flush()

    def flush(self) -> None:
        if self.stage == "debug":
            return          # debug split: raw trades carry returns; never written (PLAN 3.1)
        d = s1_dir()
        d.mkdir(parents=True, exist_ok=True)
        for name, lst in (("trades", self.trades), ("placebo", self.placebo), ("stress", self.stress)):
            if lst:
                df = pd.concat(lst, ignore_index=True)
                df.to_parquet(d / f"{self.stage}_{name}.parquet", index=False)


_DEBUG_LEDGER: Path | None = None   # set by stage_debug: debug runs go to a throwaway ledger (no means on disk)


def _run(store: _Store, label: str, fn: Callable, split: str, params: dict, hyp: str, ds: C.Dataset | None,
         placebo: bool, stress: dict | None = None) -> C.Result:
    t0 = time.time()
    res = C.backtest(fn, split, params, hypothesis=hyp, ds=ds, placebo=placebo, n_placebo=20,
                     placebo_eligible=placebo_eligible if placebo else None, stress=stress,
                     declarations=DECLARATIONS, ledger_path=_DEBUG_LEDGER if split in C.DEBUG_SPLITS else None)
    res.meta["wall_s"] = round(time.time() - t0, 2)
    store.add(label, res)
    return res


def _cfg_sensitivity(ds: C.Dataset, fn: Callable, params: dict, reveal: bool) -> dict:
    """The same config under other fill assumptions. On VAL / TEST each is a LOGGED look (its own trial: the
    ledger identity includes the fills), never a silent re-run."""
    base = C.FillConfig()
    variants = {"entry_bar_exits_off": dataclasses.replace(base, entry_bar_exits=False),
                "exit_delay_1bar": dataclasses.replace(base, exit_delay_bars=1),
                "latency_5s": dataclasses.replace(base, latency_s=5.0),
                "rent_0.22": dataclasses.replace(base, rent_usd=0.22)}
    out = {}
    for k, cfg in variants.items():
        t = C.run_trades(ds, fn, params, cfg, hypothesis=HYP,
                         ledger_path=_DEBUG_LEDGER if ds.split in C.DEBUG_SPLITS else None)
        out[k] = {"n": int(len(t)), "mean": float(t["ret_net"].mean()) if len(t) and reveal else
                  (None if not len(t) else "hidden")}
    return out


def _summ(res: C.Result, reveal: bool) -> dict:
    s = res.summary(B=10_000, reveal=reveal)
    s.pop("params", None)
    if reveal:
        pf = s.get("portfolio") or {}
        pf.pop("skipped_mints", None)
    return s


def _cp_counts(trades: pd.DataFrame) -> dict:
    if not len(trades):
        return {}
    return {str(k): int(v) for k, v in trades["tag"].value_counts().sort_index().items()}


def _write(stage: str, payload: dict, md: str) -> None:
    d = s1_dir()
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{stage}.json").write_text(json.dumps(_clean_json(payload), indent=1, sort_keys=False))
    (d / f"{stage}.md").write_text(md)


def _days(ds: C.Dataset) -> float:
    if not len(ds.coins):
        return 0.0
    c = ds.coins["created_for_split"]
    return max((float(c.max()) - float(c.min())) / 86400.0, 1e-9)


# ----------------------------------------------------------------------------------------------- gate + grid core


def _gate(store: _Store, split: str, ds: C.Dataset | None, reveal: bool) -> dict[int, dict]:
    stats = {}
    for cp in GATE_CHECKPOINTS_MIN:
        res = _run(store, f"gate_cp{cp}", gate_strategy, split, gate_params(cp), HYP_GATE, ds, placebo=False, stress={})
        stats[cp] = gate_quintiles(res.trades, reveal=reveal)
        stats[cp]["wall_s"] = res.meta["wall_s"]
    return stats


def _control1(store: _Store, split: str, ds: C.Dataset) -> C.Result:
    """Control 1, time-matched (:func:`control1_entries`): one logged look of ``S1-control1``."""
    t0 = time.time()
    p = control_params()
    if ds is None:
        ds = load_split(split)
    tr = C.run_entries(ds, control1_strategy, p, C.FillConfig(), control1_entries(ds, p), hypothesis=HYP_CTRL,
                       ledger_path=_DEBUG_LEDGER if split in C.DEBUG_SPLITS else None)
    res = C.Result(trades=tr, placebo=C._frame([], extra=("signal", "signal_mint")), stress={},
                   meta={"hypothesis": HYP_CTRL, "params": p, "split": split, "debug_only": split in C.DEBUG_SPLITS,
                         "n_coins": len(ds), "n_trials_total": C.n_trials(), "control": "time-matched (PLAN 4.3)",
                         "wall_s": round(time.time() - t0, 2)})
    store.add("control1", res)
    return res


def _grid(store: _Store, split: str, ds: C.Dataset | None, configs: list[dict], reveal: bool,
          stress: dict | None = None) -> tuple[list[dict], C.Result]:
    runs = [(p, _run(store, config_label(p), s1_strategy, split, p, HYP, ds, placebo=True, stress=stress))
            for p in configs]                       # the S1 config(s) first: on one-shot splits they matter most
    ctrl = _control1(store, split, ds)
    rows = []
    for p, res in runs:
        lab = config_label(p)
        s = _summ(res, reveal)
        d = matched_control_diff(res.trades, ctrl.trades) if reveal else {"diff": "hidden"}
        pc = s.get("placebo") if reveal else None
        rows.append({"label": lab, "params": p, "params_hash": C.params_hash(p), "n": int(len(res.trades)),
                     "n_coins": int(res.trades["mint"].nunique()) if len(res.trades) else 0,
                     "mean": s.get("mean") if reveal else "hidden",
                     "mean_without_top2": s.get("mean_without_top2") if reveal else "hidden",
                     "ci90": s.get("ci90") if reveal else "hidden",
                     "control1_diff": d["diff"], "control1_diff_ci95": d.get("ci95"),
                     "control1_weights": d.get("weights"), "control1_unmatched_cps": d.get("unmatched_cps"),
                     "placebo_diff": pc["mean_diff"] if pc else None,
                     "checkpoints": _cp_counts(res.trades), "summary": s, "result": res,
                     "new_trial": res.meta.get("new_trial"), "wall_s": res.meta["wall_s"]})
    return rows, ctrl


def _strip(rows: list[dict]) -> list[dict]:
    return [{k: v for k, v in r.items() if k != "result"} for r in rows]


# ----------------------------------------------------------------------------------------------- stages


def stage_status() -> dict:
    out = {"utc": C.utc_str(time.time()), "version": VERSION, "prereg_sha256": _prereg_sha(),
           "prereg_lock": json.loads(_lock_path().read_text()) if _lock_path().exists() else None,
           "stage_files": sorted(p.name for p in s1_dir().glob("*.json")) if s1_dir().exists() else [],
           "coverage": {}, "trials": {}}
    for sp in ("train", "val", "test", "confirm", "final_train", "final_val", "final_test"):
        try:
            out["coverage"][sp] = coverage_counts(sp)
        except Exception as e:  # noqa: BLE001 - status must never crash
            out["coverage"][sp] = {"error": repr(e)}
    with C._ledger(None, write=False) as led:
        for h in (HYP, HYP_GATE, HYP_CTRL):
            out["trials"][h] = {"configs": sum(1 for v in led["configs"].values() if v["hypothesis"] == h),
                                "runs": {sp: sum(1 for r in led["runs"] if r["hypothesis"] == h and r["split"] == sp
                                                 and not r.get("debug")) for sp in ("train", "val", "test", "confirm", "final")}}
        out["n_trials_total"] = sum(led["baseline"].values()) + len(led["configs"])
    split_of = {"train": "train", "val": "val", "test": "test", "confirm": "confirm", "final": "final"}
    for st in STAGES[2:]:
        try:
            prerequisites(st)
            out.setdefault("can_run", {})[st] = "prerequisites met"
        except StageRefused as e:
            out.setdefault("can_run", {})[st] = f"refused: {e}"
        try:
            out.setdefault("data_ready", {})[st] = check_data(split_of[st])["problems"] or "ready"
        except Exception as e:  # noqa: BLE001
            out.setdefault("data_ready", {})[st] = repr(e)
    return out


KILL_STATUSES = ("GATE_FAIL", "NO_CONFIG")


def stage_train(allow_partial: bool = False, rerun_reason: str | None = None) -> dict:
    prerequisites("train", allow_partial)
    data = check_data("train", allow_partial)
    if data["problems"]:
        raise StageRefused("TRAIN data not ready: " + "; ".join(data["problems"]))
    prelim = allow_partial and not data["split_complete"]
    name = "train_prelim" if prelim else "train"
    prev = _read_json("train.json")
    if not prelim and prev is not None and prev.get("status") in KILL_STATUSES:
        if not rerun_reason:
            raise StageRefused(f"S1 was killed on complete TRAIN ({prev['status']}); a kill is not re-rolled. "
                               "Only a data correction justifies a re-run: pass --rerun-reason '<what changed>'")
        (s1_dir() / f"train_prev_{int(time.time())}.json").write_text(json.dumps(prev, indent=1))
    if not prelim and not _lock_path().exists():
        _lock_path().write_text(json.dumps({"sha256": _prereg_sha(), "utc": C.utc_str(time.time()),
                                            "version": VERSION}, indent=1))
    ds = load_split("train")
    store = _Store(name)
    gate = _gate(store, "train", ds, reveal=True)
    gv = gate_verdict_train(gate)
    payload = {"stage": name, "version": VERSION, "utc": C.utc_str(time.time()), "preliminary": prelim,
               "rerun_reason": rerun_reason, "data": data, "n_usable_coins": len(ds), "days": _days(ds),
               "gate": gate, "gate_verdict": gv, "n_trials_total": C.n_trials()}
    if gv["status"] != "PASS":
        payload["status"] = gv["status"]
        payload["note"] = ("stop rule 3: S1 is dead (gate failed on TRAIN); the entry grid was not run"
                           if gv["status"] == "GATE_FAIL" else "gate underpowered: S1 halted; no grid, no shortlist")
        _write(name, payload, _md_train(payload))
        return payload
    rows, ctrl = _grid(store, "train", ds, grid_params(), reveal=True)
    rule = shortlist_rule(rows)
    payload.update({"grid": _strip(rows), "control1": _summ(ctrl, True), "shortlist_rule": rule,
                    "n_trials_total": C.n_trials()})
    payload["status"] = rule["status"]
    if rule["status"] == "SHORTLISTED" and not prelim:
        C.write_shortlist(HYP, rule["shortlist"], note=f"{VERSION}: PREREG §11 TRAIN shortlist rule")
        C.write_shortlist(HYP_GATE, [gate_params(cp) for cp in GATE_CHECKPOINTS_MIN], note=f"{VERSION}: gate VAL check")
        C.write_shortlist(HYP_CTRL, [control_params()], note=f"{VERSION}: control 1")
        payload["shortlists_written"] = [HYP, HYP_GATE, HYP_CTRL]
    elif prelim:
        payload["status"] = "PRELIMINARY_" + rule["status"]
        payload["note"] = "partial TRAIN: no shortlist written; re-run --stage train when TRAIN is complete"
    _write(name, payload, _md_train(payload))
    return payload


def stage_val() -> dict:
    prerequisites("val")
    data = check_data("val")
    if data["problems"]:
        raise StageRefused("VAL data not ready: " + "; ".join(data["problems"]))
    shortlist = json.loads((C.shortlist_dir() / f"{HYP}.json").read_text())["configs"]
    store = _Store("val")
    ds = load_split("val")   # every backtest below still enforces the frozen shortlists (common._check_run_allowed)
    gate = _gate(store, "val", ds, reveal=True)
    gv = gate_verdict_val(gate)
    payload = {"stage": "val", "version": VERSION, "utc": C.utc_str(time.time()), "data": data, "gate": gate,
               "gate_verdict": gv, "shortlist": shortlist}
    if gv["status"] != "PASS":
        payload["status"] = gv["status"]
        payload["note"] = ("S1 is dead: the dose-response gate failed on VAL (before any VAL run of the entry rule)"
                           if gv["status"] == "GATE_VAL_FAIL" else "gate underpowered on VAL: S1 halted")
        _write("val", payload, _md_val(payload))
        return payload
    rows, ctrl = _grid(store, "val", ds, shortlist, reveal=True)
    sel = val_selection(rows)
    payload.update({"configs": _strip(rows), "control1": _summ(ctrl, True), "selection": sel,
                    "status": sel["status"], "n_trials_total": C.n_trials()})
    if sel["status"] == "SELECTED":
        payload["sensitivity"] = _cfg_sensitivity(ds, s1_strategy, sel["selected"], reveal=True)
    _write("val", payload, _md_val(payload))
    return payload


def _val_result() -> C.Result | None:
    v = _read_json("val.json")
    p = s1_dir() / "val_trades.parquet"
    if v is None or not p.exists() or not v.get("selection", {}).get("selected"):
        return None
    lab = config_label(v["selection"]["selected"])
    t = pd.read_parquet(p)
    t = t[t["run"] == lab].drop(columns=["run"])
    return C.Result(trades=t, placebo=t.iloc[0:0], stress={}, meta={"split": "val", "hypothesis": HYP})


def _oos_stage(stage: str, split: str) -> dict:
    """TEST / CONFIRM: the frozen config once (+ control 2 + costs x1.5) and control 1 once."""
    prerequisites(stage)
    data = check_data(split)
    if data["problems"]:
        raise StageRefused(f"{split.upper()} data not ready (a one-shot run must not be wasted): "
                           + "; ".join(data["problems"]))
    v = _read_json("val.json")
    params = v["selection"]["selected"]
    ds = load_split(split)
    store = _Store(stage)
    try:
        with C.one_shot_session(HYP, split, note=f"s1 --stage {stage}"):   # S1 + control 1 + sensitivity: ONE look
            return _oos_body(stage, split, data, params, ds, store)
    except C.SplitLocked as e:
        raise StageRefused(str(e)) from e
    except Exception as e:          # the one-shot run is in the ledger: never lose its record
        _write(stage, {"stage": stage, "status": "ERROR_AFTER_RUN", "error": repr(e), "params": params,
                       "raw_files": sorted(p.name for p in s1_dir().glob(f"{stage}_*.parquet")),
                       "confirm_allowed": False, "confirm_reason": "error after the run: inspect raw files"},
               f"# S1 {stage}: ERROR after the run\n\n{e!r}\n")
        raise


def _oos_body(stage: str, split: str, data: dict, params: dict, ds: C.Dataset, store: _Store) -> dict:
    rows, ctrl = _grid(store, split, ds, [params], reveal=True, stress={"costs_x1.5": C.FillConfig().stressed(1.5)})
    res = rows[0]["result"]
    val_res = _val_result()
    ver = C.verdict_entry(res, val=val_res)
    c1 = rows[0]["control1_diff"]
    c1_needed = len(ctrl.trades) >= CTRL_MIN_TRADES_FOR_MARGIN
    payload = {"stage": stage, "version": VERSION, "utc": C.utc_str(time.time()), "data": data,
               "params": params, "label": config_label(params), "result": _strip(rows)[0],
               "control1": _summ(ctrl, True), "verdict_entry": ver,
               "control1_margin": {"diff": c1, "ci95": rows[0]["control1_diff_ci95"], "need": CONTROL_MARGIN,
                                   "applies": c1_needed,
                                   "pass": (c1 is not None and c1 >= CONTROL_MARGIN) if c1_needed else None},
               "sensitivity": _cfg_sensitivity(ds, s1_strategy, params, reveal=True),
               "n_trials_total": C.n_trials()}
    mean = rows[0]["mean"]
    if stage == "test":
        ok = mean is not None and mean > 0 and ver["verdict"] != "REJECTED"
        payload["confirm_allowed"] = bool(ok)
        payload["confirm_reason"] = "TEST mean > 0 and not REJECTED" if ok else \
            f"TEST mean {mean} / verdict {ver['verdict']}"
    _write(stage, payload, _md_oos(payload))
    return payload


def stage_test() -> dict:
    return _oos_stage("test", "test")


def stage_confirm() -> dict:
    out = _oos_stage("confirm", "confirm")
    out["overall"] = overall_verdict()
    _write("confirm", out, _md_oos(out))
    return out


def stage_final() -> dict:
    prerequisites("final")
    data = check_data("final")
    if data["problems"]:
        raise StageRefused("FINAL data not ready: " + "; ".join(data["problems"]))
    t = _read_json("test.json")
    params = t["params"]
    ds = load_split("final")
    store = _Store("final")
    res = _run(store, config_label(params), s1_strategy, "final", params, HYP, ds, placebo=True,
               stress={"costs_x1.5": C.FillConfig().stressed(1.5)})
    tr = res.trades
    per = {sp: {"n": int((tr["split"] == sp).sum()),
                "mean": float(tr.loc[tr["split"] == sp, "ret_net"].mean()) if (tr["split"] == sp).any() else None}
           for sp in C.FINAL_SPLITS}
    payload = {"stage": "final", "version": VERSION, "utc": C.utc_str(time.time()), "data": data, "params": params,
               "summary": _summ(res, True), "per_third": per,
               "final_mean_positive": bool(len(tr) and tr["ret_net"].mean() > 0),
               "note": "census TRAIN third was used for debugging only (returns hidden)"}
    payload["overall"] = overall_verdict(final=payload)
    _write("final", payload, _md_final(payload))
    return payload


def overall_verdict(final: dict | None = None) -> dict:
    """PREREG §11 overall S1 verdict from the stage files."""
    tr, v, t, c = (_read_json(n) for n in ("train.json", "val.json", "test.json", "confirm.json"))
    f = final if final is not None else _read_json("final.json")
    why = []
    if tr is None or tr.get("status") != "SHORTLISTED":
        return {"verdict": "NO EDGE" if tr and tr.get("status") in ("GATE_FAIL", "NO_CONFIG") else "INCOMPLETE",
                "why": [f"TRAIN status {tr and tr.get('status')}"]}
    if v is None or v.get("status") != "SELECTED":
        st = v and v.get("status")
        return {"verdict": "NO EDGE" if st in ("GATE_VAL_FAIL", "FAIL_VAL") else
                ("UNDERPOWERED" if st and "UNDERPOWERED" in st else "INCOMPLETE"), "why": [f"VAL status {st}"]}
    if t is None:
        return {"verdict": "INCOMPLETE", "why": ["TEST not run"]}
    if not t.get("confirm_allowed"):
        return {"verdict": "NO EDGE", "why": [f"TEST: {t.get('confirm_reason')}"]}
    sel_lab = config_label(v["selection"]["selected"])
    vm = next((r["mean"] for r in v.get("configs", []) if r["label"] == sel_lab), None)
    tm = t["result"]["mean"]
    if vm is not None and tm is not None and (vm > 0) != (tm > 0):
        why.append("TEST sign differs from VAL")
    if t["control1_margin"]["applies"] and not t["control1_margin"]["pass"]:
        why.append("TEST control-1 margin < 0.06")
    if c is None:
        return {"verdict": "INCOMPLETE", "why": why + ["CONFIRM not run"]}
    cv = c["verdict_entry"]["verdict"]
    if cv == "UNDERPOWERED" and not why:
        return {"verdict": "UNDERPOWERED", "why": ["CONFIRM < 60 trades or < 40 coins"]}
    if cv != "PASS":
        why.append(f"CONFIRM verdict {cv}")
    if not c["control1_margin"].get("pass"):
        why.append("CONFIRM control-1 margin < 0.06")
    if f is None:
        return {"verdict": "INCOMPLETE" if not why else "NO EDGE", "why": why + ["FINAL not run"]}
    if not f.get("final_mean_positive"):
        why.append("FINAL mean <= 0")
    return {"verdict": "EDGE" if not why else "NO EDGE", "why": why}


# ----------------------------------------------------------------------------------------------- debug (census TRAIN third)


def stage_debug(synthetic: bool | None = None, max_coins: int | None = None, seed: int = 0) -> dict:
    """End-to-end mechanics on the census TRAIN third (debug-only split). Counts only: returns stay hidden.
    Uses real B1 rows when they exist for these coins, else SYNTHETIC B1 (wallet flows are made up: their
    signal counts say nothing about S1; only the non-flow counts are real)."""
    t0 = time.time()
    g, c, b = _read_flow()
    cen = C.Census.load()
    ds0 = C.Dataset.from_frames("final_train", g, c, b, census=cen, guard=False)
    uni = ds0.coins[universe_mask(ds0.coins)]
    real = b1_mints() & set(uni["mint"])
    use_synth = (len(real) < B1_MIN_COVERAGE * max(len(uni), 1)) if synthetic is None else synthetic
    mints = list(uni["mint"]) if max_coins is None else list(uni["mint"])[:max_coins]
    if use_synth:
        trades = synth_b1(ds0, mints, seed=seed)
    else:
        trades = C._read_parquet(C.flow_dir() / "b1_trades.parquet")
        trades = trades[trades["mint"].isin(mints)]
    t_synth = time.time() - t0
    sub = tuple(x[x["mint"].isin(set(ds0.coins["mint"]))] for x in (g, c, b))
    ds = C.Dataset.from_frames("final_train", *sub, census=cen, trades=trades, guard=False)
    clear_cache()
    store = _Store("debug")
    global _DEBUG_LEDGER
    import tempfile
    tmpd = tempfile.TemporaryDirectory()
    _DEBUG_LEDGER = Path(tmpd.name) / "debug_trials.json"
    t1 = time.time()
    gate = _gate(store, "final_train", ds, reveal=False)
    t_gate = time.time() - t1
    t2 = time.time()
    rows, ctrl = _grid(store, "final_train", ds, grid_params(), reveal=False)
    t_grid = time.time() - t2
    _DEBUG_LEDGER = None
    tmpd.cleanup()
    days = _days(ds)
    # real (non-synthetic) counts: universe, alive at each checkpoint, bar-based ceiling for org_buyers10
    nonflow = _nonflow_counts(ds, mints)
    feats = _feature_census(ds, mints)
    payload = {
        "stage": "debug", "split": "final_train", "version": VERSION, "utc": C.utc_str(time.time()),
        "b1_source": "SYNTHETIC (made-up wallets; flow-condition counts are meaningless)" if use_synth else "real B1",
        "n_usable_coins": len(ds), "s1_universe": int(len(uni)), "coins_with_b1_rows": int(trades["mint"].nunique()),
        "b1_rows": int(len(trades)), "days": days,
        "gate": gate, "grid": [{k: r[k] for k in ("label", "n", "n_coins", "checkpoints", "new_trial", "wall_s")}
                               | {"horizon_exits": r["summary"].get("horizon_exits"),
                                  "n_placebo": r["summary"].get("n_placebo")}
                               for r in rows],
        "control1": {"n": int(len(ctrl.trades)), "checkpoints": _cp_counts(ctrl.trades)},
        "nonflow_counts_real": nonflow, "feature_census": feats,
        "timing_s": {"synth_or_load": round(t_synth, 1), "gate": round(t_gate, 1), "grid_plus_control": round(t_grid, 1)},
        "returns": "hidden (debug split: never choose parameters on FINAL data)",
    }
    _write("debug", payload, _md_debug(payload))
    return payload


def _nonflow_counts(ds: C.Dataset, mints: list[str]) -> dict:
    """REAL counts (bars + graduation columns; B1-independent): coins alive at each checkpoint, and an upper bound
    on coins that could pass org_buyers10 >= theta (sum of per-minute buyers minus the AGENT minute)."""
    days = _days(ds)
    alive = {c: 0 for c in CHECKPOINTS_MIN}
    first_ceiling = {10: 0, 20: 0}
    for m in mints:
        cd = ds.coin(m)
        got = {10: False, 20: False}
        for c in CHECKPOINTS_MIN:
            grid = cd.m0 + 60 * np.arange(1, C.N_BARS + 1) + C.GRID_OFFSET_S
            t = float(grid[grid <= cd.g + 60 * c][-1])
            s = ds.asof(m, t)
            if not s.alive():
                continue
            alive[c] += 1
            bars = s.bars
            k = s._win(600)
            agent_minutes = int((np.nan_to_num(bars.agent_buy_sol[k]) > 0).sum())   # AGENT is one buyer per minute
            nb = float(bars.n_buyers[k].sum()) - agent_minutes
            for th in (10, 20):
                if not got[th] and nb >= th:
                    got[th] = True
                    first_ceiling[th] += 1
    return {"days": days, "coins": len(mints), "alive_at_checkpoint": alive,
            "per_day_alive_at_checkpoint": {c: v / days for c, v in alive.items()},
            "ceiling_entries_theta_buy": first_ceiling,
            "ceiling_entries_per_day": {th: v / days for th, v in first_ceiling.items()}}


def _feature_census(ds: C.Dataset, mints: list[str]) -> dict:
    """Distribution of feature availability (not values) at g + 10 min: why features are NULL, class counts."""
    why, cls = {}, {}
    for m in mints:
        cd = ds.coin(m)
        grid = cd.m0 + 60 * np.arange(1, C.N_BARS + 1) + C.GRID_OFFSET_S
        t = float(grid[grid <= cd.g + 600][-1])
        f = s1_features(ds.asof(m, t))
        why[f["why"] or "ok"] = why.get(f["why"] or "ok", 0) + 1
        if f["ok"]:
            cls[f["g1_class"]] = cls.get(f["g1_class"], 0) + 1
    return {"why_at_g+10": why, "g1_class_at_g+10": cls}


# =========================================================================== synthetic B1 (DEBUG / TESTS ONLY)


def synth_b1(ds0: C.Dataset, mints: list[str], seed: int = 0, max_per_minute: int = 25) -> pd.DataFrame:
    """B1-shaped trades for coins without B1 (debug mechanics and tests ONLY; wallets and flows are made up).

    Curve phase from creation (creator + bundle in the creation slot, snipers, buyers/sellers to 85 SOL real, a
    completer buy at g), then PumpSwap: a BOOST agent (30 fee-free 12 s slices of 0.586 SOL), per-minute buys and
    sells sized from the coin's real bar flows (capped at ``max_per_minute`` each), insiders selling early, a fast
    bot, an orphan seller, and on some coins a timer (MECH-like) buyer. Reserves follow constant product on
    X = x + v with a 1.25 % fee."""
    rows = []
    fee = 0.0125
    for ci, m in enumerate(mints):
        rng = np.random.default_rng([seed, ci])
        r = ds0.coins.loc[ds0.coins["mint"] == m].iloc[0]
        cd = ds0.coin(m)
        g = int(cd.g)
        c_ts, c_slot = int(r["c_ts"]), int(r["c_slot"])
        creator = wallet_h(r["creator"]) if isinstance(r["creator"], str) and r["creator"] else int(rng.integers(1, 2**62))
        nxt = iter(range(10**9))
        wid = lambda: int(rng.integers(1, 2**63))  # noqa: E731
        pos: dict[int, int] = {}
        ins: list[int] = [creator]
        out = []

        def add(ts, venue, is_buy, w, usol, tok, x0, y0, fees, virt):
            out.append((int(ts), venue, int(is_buy), np.uint64(w), int(usol), int(tok), int(x0), int(y0), int(fees),
                        int(virt // 1000), next(nxt)))
            pos[w] = pos.get(w, 0) + (tok if is_buy else -tok)

        vx, vy = 30 * 10**9, 1_073_000_000 * 10**6

        def cbuy(ts, w, sol_lamports):
            nonlocal vx, vy
            net = int(sol_lamports * (1 - fee))
            real = vx - 30 * 10**9
            net = min(net, 85 * 10**9 - real)
            if net <= 0:
                return
            t = vy - (vx * vy) // (vx + net)
            add(ts, 0, True, w, int(net / (1 - fee)), t, vx, vy, int(net / (1 - fee)) - net, 0)
            vx, vy = vx + net, vy - t

        def csell(ts, w, t):
            nonlocal vx, vy
            gross = vx - (vx * vy) // (vy + t)
            add(ts, 0, False, w, int(gross * (1 - fee)), t, vx, vy, int(gross * fee), 0)
            vx, vy = vx - gross, vy + t

        cbuy(c_ts, creator, int(rng.uniform(0.3, 3) * 1e9))
        for _ in range(int(rng.integers(0, 3))):
            w = wid()
            ins.append(w)
            cbuy(c_ts, w, int(rng.uniform(0.5, 3) * 1e9))
        span = max(g - c_ts - 1, 2)
        for _ in range(int(rng.integers(3, 10))):
            w = wid()
            ins.append(w)
            cbuy(c_ts + int(rng.integers(1, min(60, span))), w, int(rng.uniform(0.2, 2) * 1e9))
        ts_list = np.sort(rng.integers(min(c_ts + 60, g - 1), g, size=600))
        holders = list(ins)
        for ts in ts_list:
            if vx - 30 * 10**9 >= 84 * 10**9:
                break
            if rng.random() < 0.25 and holders:
                w = holders[int(rng.integers(len(holders)))]
                if pos.get(w, 0) > 0:
                    csell(ts, w, int(pos[w] * rng.uniform(0.3, 1.0)))
                    continue
            w = wid()
            holders.append(w)
            cbuy(ts, w, int(rng.lognormal(np.log(0.5), 0.9) * 1e9))
        comp = wid()
        ins.append(comp)
        cbuy(g, comp, int(max(85 * 10**9 - (vx - 30 * 10**9), 10**8) / (1 - fee)) + 10**6)
        # ---- pool
        x, v, y = 85 * 10**9, 17_584_505_289, int(206.9e6 * 1e6)

        def pbuy(ts, w, sol_lamports, fees_on=True):
            nonlocal x, y
            f_ = fee if fees_on else 0.0
            net = int(sol_lamports * (1 - f_))
            X = x + v
            t = y * net // (X + net)
            add(ts, 1, True, w, sol_lamports, t, x, y, sol_lamports - net, v)
            x, y = x + net, y - t

        def psell(ts, w, t):
            nonlocal x, y
            if t <= 0:
                return
            X = x + v
            gross = X * t // (y + t)
            gross = min(gross, x - 10**9)
            if gross <= 0:
                return
            add(ts, 1, False, w, int(gross * (1 - fee)), t, x, y, int(gross * fee), v)
            x, y = x - gross, y + t

        agent = wid()
        events = [(g + 2 + 12 * k, "agent") for k in range(30)]
        bot = wid()
        mech = wid() if rng.random() < 0.3 else None
        if mech:
            events += [(g + 900 + 60 * k, "mech") for k in range(20)]
        a = cd.arr
        pool_buyers: list[int] = []
        for j in range(C.N_BARS):
            m_ts = cd.m0 + 60 * j
            if m_ts >= g + B1_HORIZON_S:
                break
            nb = min(int(a["n_buys"][j]), max_per_minute)
            ns = min(int(a["n_sells"][j]), max_per_minute)
            bs = max(float(a["buy_sol"][j]) - (float(a["agent_buy_sol"][j]) if np.isfinite(a["agent_buy_sol"][j]) else 0), 0)
            ss = float(a["sell_sol"][j])
            for _ in range(nb):
                events.append((int(rng.integers(max(m_ts, g + 1), m_ts + 60)), "buy", max(bs / max(nb, 1), 0.01)))
            for _ in range(ns):
                events.append((int(rng.integers(max(m_ts, g + 1), m_ts + 60)), "sell", max(ss / max(ns, 1), 0.01)))
        events.sort(key=lambda e: (e[0], e[1]))
        for e in events:
            ts, kind = e[0], e[1]
            age = (ts - g) / 60.0
            if kind == "agent":
                pbuy(ts, agent, 586_150_176, fees_on=False)
            elif kind == "mech":
                pbuy(ts, mech, 200_000_000)
            elif kind == "buy":
                if rng.random() < 0.05:
                    pbuy(ts, bot, int(e[2] * 1e9))
                    psell(ts + 3, bot, pos.get(bot, 0))
                    continue
                w = pool_buyers[int(rng.integers(len(pool_buyers)))] if pool_buyers and rng.random() < 0.3 else wid()
                pool_buyers.append(w)
                pbuy(ts, w, int(e[2] * 1e9 * rng.lognormal(0, 0.5)))
            else:
                if rng.random() < 0.03:
                    w = wid()
                    psell(ts, w, int(rng.uniform(1e5, 2e6) * 1e6))     # orphan seller (TRANSFEREE)
                    continue
                p_ins = 0.7 * math.exp(-age / 15.0)
                cands = [w for w in (ins if rng.random() < p_ins else pool_buyers) if pos.get(w, 0) > 0]
                if not cands:
                    continue
                w = cands[int(rng.integers(len(cands)))]
                psell(ts, w, int(pos[w] * rng.uniform(0.2, 1.0)))
        slot0 = c_slot
        for (ts, venue, is_buy, w, usol, tok, x0, y0, fees, vk, seq) in out:
            rows.append({"slot": slot0 + int((ts - c_ts) * 2.5), "tx_idx": seq, "pix": 0, "ix": 0, "ts": ts,
                         "venue": venue, "is_buy": is_buy, "wallet_h": w, "usol": max(usol, 10_000_000), "tok": tok,
                         "x0": x0, "y0": y0, "fees": fees, "virt_ksol": vk, "mint": m, "src": 9})
    df = pd.DataFrame(rows)
    if len(df):
        df["wallet_h"] = df["wallet_h"].astype(np.uint64)
    return df


# =========================================================================== markdown summaries


def _f(x, pct=True):
    if x is None:
        return "–"
    if isinstance(x, str):
        return x
    return f"{x:+.2%}" if pct else f"{x:.3g}"


def _md_gate(gate: dict) -> list[str]:
    out = ["| Checkpoint | n | Q1 | Q2 | Q3 | Q4 | Q5 | Inversions | Q1 − Q5 |", "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for cp, s in gate.items():
        qs = s.get("quintiles") or []
        cells = [_f(q["mean"]) for q in qs] + ["–"] * (5 - len(qs))
        out.append(f"| g + {cp} min | {s['n']} | " + " | ".join(cells) + f" | {s.get('inversions')} | {_f(s.get('q1_minus_q5'))} |")
    return out


def _md_train(p: dict) -> str:
    L = [f"# S1 {p['stage']}: {p['status']}", "", f"- Version `{VERSION}`, run {p['utc']} UTC; "
         f"{p['n_usable_coins']} usable coins over {p['days']:.2f} days.",
         f"- B1 covers {p['data']['b1_covered']}/{p['data']['s1_universe']} S1-universe coins.",
         f"- Trials so far (deflated Sharpe): {p.get('n_trials_total')}.", "", "## Dose-response gate (30-minute hold)", ""]
    L += _md_gate(p["gate"]) + ["", f"Gate verdict: **{p['gate_verdict']['status']}** {p['gate_verdict']['per_checkpoint']}."]
    if p.get("note"):
        L += ["", p["note"]]
    if p.get("grid"):
        L += ["", "## Grid (8 configs; every one is a trial)", "",
              "| Config | n | Coins | Mean | Mean w/o top 2 | 90% CI | vs control 1 | vs placebo |",
              "|---|---:|---:|---:|---:|---|---:|---:|"]
        for r in p["grid"]:
            ci = r["ci90"]
            ci_s = f"[{_f(ci[0])}, {_f(ci[1])}]" if isinstance(ci, list) else "–"
            L.append(f"| {r['label']} | {r['n']} | {r['n_coins']} | {_f(r['mean'])} | {_f(r['mean_without_top2'])} | "
                     f"{ci_s} | {_f(r['control1_diff'])} | {_f(r['placebo_diff'])} |")
        L += ["", f"Shortlist rule: **{p['shortlist_rule']['status']}**; ranked: {p['shortlist_rule']['ranked']}."]
    return "\n".join(L) + "\n"


def _md_val(p: dict) -> str:
    L = [f"# S1 VAL: {p['status']}", "", f"- Run {p['utc']} UTC.", "", "## Gate on VAL", ""]
    L += _md_gate(p["gate"]) + ["", f"Gate verdict: **{p['gate_verdict']['status']}**."]
    if p.get("note"):
        L += ["", p["note"]]
    for r in p.get("configs", []):
        L.append(f"- {r['label']}: n {r['n']}, mean {_f(r['mean'])}, vs control 1 {_f(r['control1_diff'])}, "
                 f"vs placebo {_f(r['placebo_diff'])}")
    if p.get("selection"):
        L.append(f"\nSelection: **{p['selection']['status']}**.")
    return "\n".join(L) + "\n"


def _md_oos(p: dict) -> str:
    r = p["result"]
    ver = p["verdict_entry"]
    L = [f"# S1 {p['stage'].upper()}: {ver['verdict']}", "", f"- Config `{p['label']}`; run {p['utc']} UTC.",
         f"- n {r['n']} trades from {r['n_coins']} coins; mean {_f(r['mean'])}; 90% CI {r['ci90']}.",
         f"- Control-1 margin {_f(p['control1_margin']['diff'])} (need ≥ +6.00% when it applies: "
         f"{p['control1_margin']['applies']}).", "", "| # | Criterion | Pass | Value |", "|---:|---|---|---|"]
    for c in ver["criteria"]:
        L.append(f"| {c['id']} | {c['name']} | {c['pass']} | {json.dumps(_clean_json(c['value']))[:80]} |")
    if ver["auto_rejections"]:
        L += ["", f"Auto-rejections: {ver['auto_rejections']}"]
    if p.get("overall"):
        L += ["", f"Overall S1 verdict: **{p['overall']['verdict']}** {p['overall']['why']}"]
    return "\n".join(L) + "\n"


def _md_final(p: dict) -> str:
    s = p["summary"]
    L = [f"# S1 FINAL (census day): mean {_f(s.get('mean'))}, n {s.get('n')}", "",
         f"- Per third: {json.dumps(_clean_json(p['per_third']))}", f"- {p['note']}",
         f"- Overall S1 verdict: **{p['overall']['verdict']}** {p['overall']['why']}"]
    return "\n".join(L) + "\n"


def _md_debug(p: dict) -> str:
    nf = p["nonflow_counts_real"]
    L = ["# S1 debug run on the census TRAIN third (counts only; returns hidden)", "",
         f"- B1 source: **{p['b1_source']}**.",
         f"- {p['n_usable_coins']} usable coins; S1-universe {p['s1_universe']}; {p['days']:.2f} days; "
         f"{p['b1_rows']} B1 rows.",
         f"- Timing (s): {p['timing_s']}.", "", "## Gate populations", ""]
    for cp, s in p["gate"].items():
        L.append(f"- g + {cp} min: {s['n']} coins, quintile sizes {[q['n'] for q in s.get('quintiles', [])]}.")
    L += ["", "## Grid signal counts (synthetic flows if so marked: meaningless for S1's rate)", "",
          "| Config | n | Coins | By checkpoint |", "|---|---:|---:|---|"]
    for r in p["grid"]:
        L.append(f"| {r['label']} | {r['n']} | {r['n_coins']} | {r['checkpoints']} |")
    L += ["", f"Control 1: {p['control1']}.", "", "## Real non-flow counts (bars + graduation columns)", "",
          f"- Alive at each checkpoint: {nf['alive_at_checkpoint']}.",
          f"- Per day: { {k: round(v, 1) for k, v in nf['per_day_alive_at_checkpoint'].items()} }.",
          f"- Upper bound on entries (alive and ≥ θ_buy buyers in 10 min, first checkpoint): "
          f"{nf['ceiling_entries_theta_buy']} → per day "
          f"{ {k: round(v, 1) for k, v in nf['ceiling_entries_per_day'].items()} }.",
          f"- Feature availability at g + 10 min: {p['feature_census']}."]
    return "\n".join(L) + "\n"


# =========================================================================== CLI


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stage", required=True, choices=STAGES)
    ap.add_argument("--allow-partial", action="store_true", help="TRAIN only: PRELIMINARY run on incomplete TRAIN")
    ap.add_argument("--rerun-reason", default=None, help="TRAIN only: data correction that justifies re-running a kill")
    ap.add_argument("--synthetic", choices=["auto", "yes", "no"], default="auto", help="debug only: synthetic B1")
    ap.add_argument("--max-coins", type=int, default=None, help="debug only: limit the number of coins")
    a = ap.parse_args(argv)
    if a.allow_partial and a.stage != "train":
        ap.error("--allow-partial applies to --stage train only")
    try:
        if a.stage == "status":
            out = stage_status()
            print(json.dumps(_clean_json(out), indent=1))
            return 0
        fn = {"debug": lambda: stage_debug({"auto": None, "yes": True, "no": False}[a.synthetic], a.max_coins),
              "train": lambda: stage_train(a.allow_partial, a.rerun_reason), "val": stage_val, "test": stage_test,
              "confirm": stage_confirm, "final": stage_final}[a.stage]
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=RuntimeWarning)
            out = fn()
    except (StageRefused, C.SplitLocked) as e:
        print(f"REFUSED: --stage {a.stage}: {e}", file=sys.stderr)
        return 2
    name = out.get("stage", a.stage)
    print(f"S1 {name}: {out.get('status', out.get('verdict_entry', {}).get('verdict', 'done'))} -> "
          f"{s1_dir() / (name + '.json')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
