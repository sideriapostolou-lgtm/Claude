"""P4b: B1 wallet-level trades for lab2 S1 and D1, fetched in packed time slabs (``sql/b1c.sql``).

Why not P4 (``sql/b1.sql``, coin batches): every coin window [created, g + 120 min) scans >= 2.25 h of chain
time (~245 M rows, 60-80 s at 3-4 M rows/s: timeouts), 6.5 % of coins are too big for the 1 MB cap even alone,
and batches of 4 need ~7.5 queries per chain hour (scratchpad ``flow/B1_PLAN.md``).

P4b instead:

* **Selection** = the S1 universe (``research/lab2/b1_select.py`` -> ``FLOW/b1_select.json``): usable, creation
  scanned, created_exact, grad_delay > 5 s. Window [c_ts, g_ts + 7200). Every filter is a graduation-time fact.
* **Estimate** trades per (coin, clock minute) offline: pool trades = B2 ``n_buys + n_sells - n_dust`` (exact on
  the pilot), curve trades = 0.95 x (launch trades over [c, c + 120 s) + the rest of the curve life spread evenly).
* **Pack** (:func:`pack`): sweep minutes in time order, every active coin in a fixed order, 43 B per estimated trade
  + 60 B per piece with trades; close the unit when it would pass ``target`` (920 kB) or its span reaches 30 min.
  A coin's window becomes consecutive pieces, no gaps, no overlaps. Packing runs on each coin's RESIDUAL (window
  minus what is already fetched), so a restart or a newly selected coin just re-packs what is missing.
* **Run** (:class:`Runner`): one query per unit through the shared client (query log, flock, rolling-hour budget);
  the chunk (with its pieces) is saved to ``raw/b1c/`` BEFORE ``state_b1.json`` is updated. ResultTooLarge splits
  the unit at its time midpoint (a single minute by coin halves); QueryTimeout splits it at a 15-minute anchor
  (slot ranges come from 15-minute anchors, so a smaller split would read the same rows) or, inside one anchor,
  retries it later (``TIMEOUT_TRIES`` per coin, then the coin is an error); ``n_overflow > 0`` marks the coin.
* **Consolidate** (:func:`consolidate_b1`): decode to the ``b1_trades.parquet`` schema, sort per coin, drop
  duplicate keys, forward-fill the pool virtual reserve on piece-start sells, write ONLY coins whose fetched pieces
  cover [c, g + 7200), plus ``b1_coins.parquet`` (per-coin pieces / completeness / B1 = B2 gate) and
  ``b1_manifest.json`` (coverage per split).
"""

from __future__ import annotations

import gzip
import hashlib
import json
import logging
import math
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

log = logging.getLogger("b1c")

B1_HORIZON_S = 7200            # window = [created, g + 120 min): S1/D1 read ts < g + 7200
MIN_USOL = 10_000_000          # dust < 0.01 SOL dropped (as b1.sql / B2 n_dust)
BYTES_PER_TRADE = 43.0         # compact tuple (byteSize, measured M2/M4)
BYTES_PER_PIECE = 60.0         # per-piece row overhead (mint, lo, counters, array offsets)
TARGET_BYTES = 920_000         # server cap 1 MB native; estimates over-estimate slab totals by 1-2.5 %
MAX_SCAN_S = 30 * 60           # unit span cap (30-min slabs: 5-18 s measured, <= 38 s at 2.9 M rows/s)
MAX_PIECES = 1500              # result-row cap is 2,000 (never binds: ~25-60 active coins per slab)
CURVE_ND = 0.95                # curve non-dust share of curve_n_buys + curve_n_sells (93-98 % measured)
LAUNCH_S = 120
TIMEOUT_TRIES = 3              # minimal (one-anchor) units that time out are retried; then the coin is an error
GATE_TOL = 0.005               # B1 pool trades per minute vs B2 non-dust count: flag above 0.5 %
Q15 = 900

# compact tuple of sql/b1c.sql (index -> meaning) and the decoded b1_trades.parquet schema
COMPACT_FIELDS = ("slot", "tx_idx", "pix", "ix", "off", "flags", "wallet_h", "usol_u", "tok_w", "x0_f32", "y0_w",
                  "fees_u", "virt_ksol")
TRADE_COLUMNS = ("slot", "tx_idx", "pix", "ix", "ts", "venue", "is_buy", "wallet_h", "usol", "tok", "x0", "y0",
                 "fees", "virt_ksol")
KEY = ("slot", "tx_idx", "pix", "ix")


def utc(ts: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(float(ts)))


# =========================================================================== intervals


def merge_intervals(iv: Iterable[Sequence[int]]) -> list[list[int]]:
    out: list[list[int]] = []
    for a, b in sorted((int(a), int(b)) for a, b in iv if int(b) > int(a)):
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


def subtract(lo: int, hi: int, covered: Iterable[Sequence[int]]) -> list[tuple[int, int]]:
    """[lo, hi) minus the covered intervals, as sorted disjoint intervals."""
    out, x = [], int(lo)
    for a, b in merge_intervals(covered):
        if b <= x:
            continue
        if a >= hi:
            break
        if a > x:
            out.append((x, min(a, hi)))
        x = max(x, b)
        if x >= hi:
            break
    if x < hi:
        out.append((x, int(hi)))
    return out


def covers(iv: Iterable[Sequence[int]], lo: int, hi: int) -> bool:
    return not subtract(lo, hi, iv)


# =========================================================================== selection


@dataclass(frozen=True)
class Coin:
    mint: str
    pool: str
    lo: int          # c_ts
    hi: int          # g_ts + 7200
    split: str


def load_selection(path: Path) -> dict[str, list[Coin]]:
    """``FLOW/b1_select.json`` (research/lab2/b1_select.py) -> split -> coins in creation order."""
    doc = json.loads(Path(path).read_text())
    out: dict[str, list[Coin]] = {}
    for split, d in (doc.get("splits") or {}).items():
        cs = [Coin(str(m), str(p or ""), int(lo), int(hi), split) for m, p, lo, hi in d.get("coins") or []]
        out[split] = sorted(cs, key=lambda c: (c.lo, c.mint))
    return out


# =========================================================================== estimator


def _spread(est: dict[int, float], a: float, b: float, n: float) -> None:
    """Add ``n`` trades spread uniformly over [a, b) to the clock minutes it overlaps."""
    if n <= 0:
        return
    a, b = float(a), float(max(b, a + 1))
    m = int(a // 60) * 60
    while m < b:
        ov = min(b, m + 60) - max(a, m)
        if ov > 0:
            est[m] = est.get(m, 0.0) + n * ov / (b - a)
        m += 60


def estimate_minutes(c_ts: float, g_ts: float, lo: int, hi: int, curve_n: float, launch_n: float,
                     pool_nd: Mapping[int, float] | None) -> dict[int, float]:
    """Estimated B1 (non-dust) trades per clock minute of the window [lo, hi).

    ``curve_n`` = curve_n_buys + curve_n_sells, ``launch_n`` = l_n_buys + l_n_sells (dust included, both from
    graduates.parquet), ``pool_nd`` = {minute_ts: n_buys + n_sells - n_dust} from b2_bars.parquet."""
    est: dict[int, float] = {}
    c, g = float(c_ts), float(g_ts)
    tot = CURVE_ND * max(float(curve_n or 0.0), 0.0)
    launch = min(tot, CURVE_ND * max(float(launch_n or 0.0), 0.0))
    if g > c + LAUNCH_S:
        _spread(est, c, c + LAUNCH_S, launch)
        _spread(est, c + LAUNCH_S, g, tot - launch)
    else:
        _spread(est, c, max(g, c + 1), tot)
    g_min = int(g // 60) * 60
    for m, nd in (pool_nd or {}).items():
        m = int(m)
        if m < g_min or m >= hi or m + 60 <= lo or not nd:
            continue
        frac = (min(hi, m + 60) - max(lo, m)) / 60.0          # the window's last minute is partial
        est[m] = est.get(m, 0.0) + float(nd) * frac
    return {m: v for m, v in est.items() if lo - 60 < m < hi}


def estimates_from_frames(coins: Sequence[Coin], graduates, bars) -> dict[str, dict[int, float]]:
    """Per-coin minute estimates from graduates.parquet / b2_bars.parquet frames (pandas)."""
    want = {c.mint for c in coins}
    g = graduates[graduates["mint"].isin(want)]
    gi = {r["mint"]: r for r in g.to_dict("records")}
    b = bars[bars["mint"].isin(want)]
    nd = (b["n_buys"] + b["n_sells"] - b["n_dust"]).to_numpy(float)
    pool_nd: dict[str, dict[int, float]] = defaultdict(dict)
    for mint, m, n in zip(b["mint"].to_numpy(object), b["minute_ts"].to_numpy(np.int64), nd):
        pool_nd[mint][int(m)] = pool_nd[mint].get(int(m), 0.0) + float(n)
    out = {}
    for c in coins:
        r = gi.get(c.mint, {})
        cn = _num(r.get("curve_n_buys")) + _num(r.get("curve_n_sells"))
        ln = _num(r.get("l_n_buys")) + _num(r.get("l_n_sells"))
        gts = _num(r.get("g_ts")) or (c.hi - B1_HORIZON_S)
        out[c.mint] = estimate_minutes(c.lo, gts, c.lo, c.hi, cn, ln, pool_nd.get(c.mint))
    return out


def _num(x: Any) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if math.isnan(v) else v


# =========================================================================== packing


@dataclass
class Unit:
    """One query: pieces [mint, pool, lo, hi] (each a coin's window cut to the slab), with its estimate."""

    pieces: list[list] = field(default_factory=list)
    est_bytes: float = 0.0
    est_trades: float = 0.0

    @property
    def t0(self) -> int:
        return min(int(p[2]) for p in self.pieces)

    @property
    def t1(self) -> int:
        return max(int(p[3]) for p in self.pieces)

    @property
    def span(self) -> int:
        return self.t1 - self.t0

    def key(self) -> str:
        h = hashlib.sha1(";".join(f"{m},{a},{b}" for m, _p, a, b in sorted(self.pieces)).encode()).hexdigest()[:10]
        return f"{self.t0}-{self.t1}-{h}"


def pack(items: Sequence[Mapping[str, Any]], target: float = TARGET_BYTES, max_scan_s: int = MAX_SCAN_S,
         bpt: float = BYTES_PER_TRADE, bpp: float = BYTES_PER_PIECE, max_pieces: int = MAX_PIECES) -> list[Unit]:
    """Sweep packer. ``items``: {mint, pool, lo, hi (the coin window), residual [(a, b)...], est {minute: trades}}.

    Minutes in time order; inside a minute every active coin in mint order adds its estimated bytes (``bpt`` per
    trade, ``bpp`` once per piece with trades; a coin-minute with 0 estimated trades costs nothing but is still
    assigned). The open unit closes when the next cell would push it past ``target`` or when the minute is
    ``max_scan_s`` past the unit's first minute; the next unit starts at that minute for the coins not yet
    assigned it. Returns units in time order; every coin's residual is cut into consecutive pieces."""
    cells: dict[int, list[tuple]] = defaultdict(list)
    for it in sorted(items, key=lambda d: d["mint"]):
        lo, hi = int(it["lo"]), int(it["hi"])
        est = it.get("est") or {}
        for a, b in it["residual"]:
            a, b = int(a), int(b)
            m = a // 60 * 60
            while m < b:
                sa, sb = max(a, m), min(b, m + 60)
                wa, wb = max(lo, m), min(hi, m + 60)
                e = float(est.get(m, 0.0)) * (sb - sa) / max(wb - wa, 1)
                cells[m].append((it["mint"], it.get("pool") or "", sa, sb, e))
                m += 60
    units: list[Unit] = []
    cur: Unit | None = None
    start = 0
    open_piece: dict[str, list] = {}
    trading: set[str] = set()

    def close():
        nonlocal cur
        if cur is not None and cur.pieces:
            units.append(cur)
        cur = None
        open_piece.clear()
        trading.clear()

    for m in sorted(cells):
        if cur is not None and m - start >= max_scan_s:
            close()
        for mint, pool, a, b, e in sorted(cells[m]):
            if cur is not None and cur.pieces:
                new_piece = mint not in open_piece or open_piece[mint][3] != a
                add = bpt * e + (bpp if e > 0 and mint not in trading else 0.0)
                if cur.est_bytes + add > target or (new_piece and len(cur.pieces) >= max_pieces):
                    close()
            if cur is None:
                cur, start = Unit(), m
            new_piece = mint not in open_piece or open_piece[mint][3] != a
            add = bpt * e + (bpp if e > 0 and mint not in trading else 0.0)
            if new_piece:
                p = [mint, pool, a, b]
                cur.pieces.append(p)
                open_piece[mint] = p
            else:
                open_piece[mint][3] = b
            if e > 0:
                trading.add(mint)
            cur.est_bytes += add
            cur.est_trades += e
    close()
    return units


def split_time(u: Unit, mid: int) -> tuple[Unit, Unit]:
    """Cut a unit at ``mid``: pieces left of it, right of it, straddling pieces cut in two (estimates by time)."""
    left, right = Unit(), Unit()
    for m, p, a, b in u.pieces:
        if b <= mid:
            left.pieces.append([m, p, a, b])
        elif a >= mid:
            right.pieces.append([m, p, a, b])
        else:
            left.pieces.append([m, p, a, mid])
            right.pieces.append([m, p, mid, b])
    span = max(u.span, 1)
    for h in (left, right):
        if h.pieces:
            f = h.span / span
            h.est_bytes, h.est_trades = u.est_bytes * f, u.est_trades * f
    return left, right


def split_pieces(u: Unit) -> tuple[Unit, Unit]:
    k = len(u.pieces) // 2
    a, b = Unit(u.pieces[:k]), Unit(u.pieces[k:])
    for h in (a, b):
        f = len(h.pieces) / len(u.pieces)
        h.est_bytes, h.est_trades = u.est_bytes * f, u.est_trades * f
    return a, b


def split_too_large(u: Unit) -> tuple[Unit, Unit] | None:
    """ResultTooLarge: split at the time midpoint (minute-aligned when possible); a unit inside one minute is
    split by coin halves; one piece inside one minute is split by seconds; one second: give up (None)."""
    t0, t1 = u.t0, u.t1
    if t1 - t0 > 60:
        mid = (t0 + (t1 - t0) // 2) // 60 * 60
        if not t0 < mid < t1:
            mid = t0 // 60 * 60 + 60
        if not t0 < mid < t1:
            mid = t0 + (t1 - t0) // 2
        return split_time(u, mid)
    if len(u.pieces) > 1:
        return split_pieces(u)
    if t1 - t0 > 1:
        return split_time(u, t0 + (t1 - t0) // 2)
    return None


def split_timeout(u: Unit) -> tuple[Unit, Unit] | None:
    """QueryTimeout: split at the 15-minute anchor nearest the middle (rows read follow the anchors); None when
    the unit lies inside one anchor bucket (splitting cannot reduce the scan: retry it later)."""
    t0, t1 = u.t0, u.t1
    cand = [b for b in range(t0 // Q15 * Q15 + Q15, t1, Q15) if t0 < b < t1]
    if not cand:
        return None
    mid = min(cand, key=lambda b: abs(b - (t0 + t1) / 2))
    return split_time(u, mid)


# =========================================================================== decoding


def decode_trades(lo: int, trades: Sequence[Sequence[Any]]) -> dict[str, np.ndarray]:
    """Compact tuples of one piece -> b1_trades.parquet columns (lamports, raw token units)."""
    if not trades:
        return {k: np.zeros(0, np.uint64 if k == "wallet_h" else np.int64) for k in TRADE_COLUMNS}
    cols = list(zip(*trades))
    i64 = lambda j: np.asarray(cols[j], dtype=np.int64)  # noqa: E731
    flags = i64(5)
    return {
        "slot": i64(0), "tx_idx": i64(1), "pix": i64(2), "ix": i64(3),
        "ts": i64(4) + int(lo),
        "venue": flags & 1, "is_buy": flags >> 1,
        "wallet_h": np.asarray(cols[6], dtype=np.uint64),
        "usol": i64(7) * 1000, "tok": i64(8) * 1_000_000,
        "x0": np.rint(np.asarray(cols[9], dtype=np.float64)).astype(np.int64),
        "y0": i64(10) * 1_000_000, "fees": i64(11) * 1000, "virt_ksol": i64(12),
    }


def ffill_virt(venue: np.ndarray, virt: np.ndarray) -> tuple[np.ndarray, int]:
    """Pool rows (venue 1) with virt 0 after the coin's first non-zero value take the previous non-zero value
    (a piece restarts the chain carry, so its sells before its first buy come back 0). Rows before the coin's first
    non-zero value stay 0, as in an unpieced b1.sql window. Returns (virt, number of rows filled)."""
    v = np.array(virt, dtype=np.int64, copy=True)
    idx = np.flatnonzero(np.asarray(venue) == 1)
    if not len(idx):
        return v, 0
    pv = v[idx]
    nz = pv > 0
    last = np.maximum.accumulate(np.where(nz, np.arange(len(pv)), -1))
    fill = (~nz) & (last >= 0)
    pv[fill] = pv[last[fill]]
    v[idx] = pv
    return v, int(fill.sum())


def sort_dedup(cols: dict[str, np.ndarray]) -> tuple[dict[str, np.ndarray], int]:
    """Sort by (slot, tx_idx, pix, ix) and drop rows whose key repeats (a piece fetched twice)."""
    n = len(cols["slot"])
    if not n:
        return cols, 0
    order = np.lexsort((cols["ix"], cols["pix"], cols["tx_idx"], cols["slot"]))
    s = {k: v[order] for k, v in cols.items()}
    keep = np.ones(n, bool)
    keep[1:] = ~((s["slot"][1:] == s["slot"][:-1]) & (s["tx_idx"][1:] == s["tx_idx"][:-1])
                 & (s["pix"][1:] == s["pix"][:-1]) & (s["ix"][1:] == s["ix"][:-1]))
    if keep.all():
        return s, 0
    return {k: v[keep] for k, v in s.items()}, int((~keep).sum())


# =========================================================================== consolidation (offline)


def iter_chunks(out: Path):
    d = Path(out) / "raw" / "b1c"
    if not d.exists():
        return
    for p in sorted(d.glob("*.json.gz")):
        with gzip.open(p, "rt") as f:
            yield p.name, json.load(f)


def consolidate_b1(out: Path, grads: Mapping[str, Mapping[str, Any]], pool_nd: Mapping[str, Mapping[int, float]],
                   selection: Mapping[str, Sequence[Coin]] | None = None) -> dict[str, Any]:
    """Decode ``raw/b1c`` chunks. Returns {"trades": columns (complete coins only, sorted by mint then key) or None,
    "coins": per-coin rows for b1_coins.parquet, "manifest": per-split coverage, "summary"}.

    ``grads`` = mint -> graduates row (c_ts, g_ts, has_create, pool): the canonical window [c_ts, g_ts + 7200).
    ``pool_nd`` = pool -> {minute_ts: B2 non-dust trades} for the B1 = B2 gate.
    A coin is complete only when its fetched pieces (overflowed pieces excluded) cover the whole window; only
    complete coins are written."""
    cov: dict[str, list] = defaultdict(list)
    parts: dict[str, list[dict]] = defaultdict(list)
    overflow: dict[str, int] = defaultdict(int)
    n_pieces: dict[str, int] = defaultdict(int)
    chunks_of: dict[str, set] = defaultdict(set)
    pool_of: dict[str, str] = {}
    n_chunks = 0
    for name, ch in iter_chunks(out):
        n_chunks += 1
        rows = {(d["mint"], int(d["lo"])): d for d in (dict(zip(ch["columns"], r)) for r in ch["rows"])}
        for mint, pool, a, b in ch["pieces"]:
            a, b = int(a), int(b)
            pool_of.setdefault(mint, pool)
            d = rows.get((mint, a))
            n_pieces[mint] += 1
            chunks_of[mint].add(name)
            if d is not None and (int(d.get("n_overflow") or 0) > 0 or len(d["trades"]) != int(d["n_trades"])):
                overflow[mint] += 1
                continue
            cov[mint].append((a, b))
            if d is not None and d["trades"]:
                cols = decode_trades(a, d["trades"])
                inside = (cols["ts"] >= a) & (cols["ts"] < b)
                if not inside.all():
                    cols = {k: v[inside] for k, v in cols.items()}
                parts[mint].append(cols)
    split_of = {c.mint: s for s, cs in (selection or {}).items() for c in cs}
    mints = sorted(set(cov) | set(overflow) | set(split_of))
    coin_rows, keep_cols, n_rows_total = [], [], 0
    for mint in mints:
        g = grads.get(mint) or {}
        c_ts = g.get("c_ts") if g.get("has_create") else None
        g_ts = g.get("g_ts")
        lo = int(c_ts) if c_ts is not None else None
        hi = int(g_ts) + B1_HORIZON_S if g_ts is not None else None
        iv = merge_intervals(cov.get(mint, []))
        complete = lo is not None and hi is not None and covers(iv, lo, hi)
        missing = sum(b - a for a, b in subtract(lo, hi, iv)) if lo is not None and hi is not None else None
        row = {"mint": mint, "pool": g.get("pool") or pool_of.get(mint), "split": split_of.get(mint),
               "selected": mint in split_of, "c_ts": lo, "g_ts": int(g_ts) if g_ts is not None else None,
               "lo": lo, "hi": hi, "complete": bool(complete), "missing_s": missing, "n_pieces": n_pieces.get(mint, 0),
               "n_chunks": len(chunks_of.get(mint, ())), "overflow_pieces": overflow.get(mint, 0),
               "pieces": json.dumps(iv), "n_trades": 0, "n_pool_trades": 0, "n_dup_dropped": 0, "n_virt_ffilled": 0,
               "gate_b1_pool": None, "gate_b2_pool": None, "gate_abs_diff": None, "gate_ok": None}
        if complete:
            ps = parts.get(mint) or []
            cols = {k: np.concatenate([p[k] for p in ps]) for k in TRADE_COLUMNS} if ps else decode_trades(0, [])
            win = (cols["ts"] >= lo) & (cols["ts"] < hi)
            if not win.all():
                cols = {k: v[win] for k, v in cols.items()}
            cols, ndup = sort_dedup(cols)
            cols["virt_ksol"], nfill = ffill_virt(cols["venue"], cols["virt_ksol"])
            n = len(cols["slot"])
            row.update({"n_trades": n, "n_pool_trades": int((cols["venue"] == 1).sum()), "n_dup_dropped": ndup,
                        "n_virt_ffilled": nfill})
            row.update(gate(cols, g_ts, hi, (pool_nd or {}).get(row["pool"] or "")))
            if n:
                cols["mint"] = np.full(n, mint, dtype=object)
                keep_cols.append(cols)
                n_rows_total += n
        coin_rows.append(row)
    trades = None
    if keep_cols:
        trades = {k: np.concatenate([c[k] for c in keep_cols]) for k in (*TRADE_COLUMNS, "mint")}
        trades["src"] = np.zeros(n_rows_total, np.int64)
    man = manifest(coin_rows, selection)
    summary = {"b1c_chunks": n_chunks, "b1_coins_seen": len(coin_rows),
               "b1_coins_complete": sum(1 for r in coin_rows if r["complete"]), "b1_trades": n_rows_total,
               "b1_gate_flagged": sum(1 for r in coin_rows if r["gate_ok"] is False)}
    return {"trades": trades, "coins": coin_rows, "manifest": man, "summary": summary}


def gate(cols: Mapping[str, np.ndarray], g_ts: float, hi: int, b2_nd: Mapping[int, float] | None) -> dict:
    """B1 pool trades per clock minute vs B2's non-dust count over the minutes fully inside [g, hi)."""
    if b2_nd is None:
        return {"gate_b1_pool": None, "gate_b2_pool": None, "gate_abs_diff": None, "gate_ok": None}
    m_lo, m_hi = int(g_ts) // 60 * 60, int(hi) // 60 * 60
    pool = cols["venue"] == 1
    mins = cols["ts"][pool] // 60 * 60
    mins = mins[(mins >= m_lo) & (mins < m_hi)]
    b1 = defaultdict(int)
    for m, k in zip(*np.unique(mins, return_counts=True)):
        b1[int(m)] = int(k)
    b2 = {int(m): float(n) for m, n in b2_nd.items() if m_lo <= int(m) < m_hi}
    keys = set(b1) | set(b2)
    diff = sum(abs(b1.get(m, 0) - b2.get(m, 0.0)) for m in keys)
    t1, t2 = sum(b1.values()), sum(b2.values())
    return {"gate_b1_pool": int(t1), "gate_b2_pool": int(round(t2)), "gate_abs_diff": int(round(diff)),
            "gate_ok": bool(diff <= GATE_TOL * max(t2, 1.0))}


def manifest(coin_rows: Sequence[Mapping[str, Any]], selection: Mapping[str, Sequence[Coin]] | None) -> dict:
    """Per split: selected coins (b1_select.json), complete coins and the fraction (S1/D1 need >= 95 %)."""
    by = {r["mint"]: r for r in coin_rows}
    out = {}
    for split, cs in (selection or {}).items():
        rows = [by.get(c.mint) or {} for c in cs]
        done = [r for r in rows if r.get("complete")]
        inc = [c.mint for c, r in zip(cs, rows) if not r.get("complete")]
        out[split] = {
            "selected": len(cs), "complete": len(done),
            "frac": round(len(done) / len(cs), 4) if cs else None,
            "incomplete": len(inc), "incomplete_first": inc[:20],
            "with_overflow": sum(1 for r in rows if r.get("overflow_pieces")),
            "gate_flagged": sum(1 for r in done if r.get("gate_ok") is False),
            "gate_unchecked": sum(1 for r in done if r.get("gate_ok") is None),
            "trades": int(sum(r.get("n_trades") or 0 for r in done)),
            "virt_ffilled_rows": int(sum(r.get("n_virt_ffilled") or 0 for r in done)),
        }
    return out


# =========================================================================== runner (queries)


class Runner:
    """P4b driver on top of ``backfill.Backfill`` (its client, slot map, stop rules and ``state_b1.json`` store)."""

    def __init__(self, bf, selection: Mapping[str, Sequence[Coin]], splits: Sequence[str],
                 estimates: Mapping[str, Mapping[int, float]], target: float = TARGET_BYTES,
                 max_scan_s: int = MAX_SCAN_S, retry_errors: bool = False, timeout_backoff_s: float = 60.0,
                 render=None, sleep=time.sleep):
        from decode import render_sql, sql_in, sql_tuples   # local: keep the offline helpers import-light
        self.bf = bf
        self.sel = selection
        self.splits = list(splits)
        self.est = estimates
        self.target, self.max_scan_s = float(target), int(max_scan_s)
        self.backoff = float(timeout_backoff_s)
        self.sleep = sleep
        self.render = render or render_sql
        self._sql_in, self._sql_tuples = sql_in, sql_tuples
        st = bf.store.state.setdefault("b1c", {})
        for k in ("cov", "err", "tmo", "units"):
            st.setdefault(k, {})
        self.st = st
        self.run_stats: dict[str, dict] = {s: {"queries": 0, "units_ok": 0, "splits_large": 0, "splits_timeout": 0,
                                               "timeouts_deferred": 0, "errors": 0} for s in self.splits}
        if retry_errors:
            mine = {c.mint for s in self.splits for c in selection.get(s, ())}
            for k in ("err", "tmo"):
                for m in [m for m in st[k] if m in mine]:
                    del st[k][m]
            bf.store.save_state()

    # -- planning ------------------------------------------------------------------------------------

    def residual(self, c: Coin) -> list[tuple[int, int]]:
        return subtract(c.lo, c.hi, self.st["cov"].get(c.mint, []))

    def items(self, split: str) -> list[dict]:
        out = []
        for c in self.sel.get(split, ()):
            if c.mint in self.st["err"]:
                continue
            r = self.residual(c)
            if r:
                out.append({"mint": c.mint, "pool": c.pool, "lo": c.lo, "hi": c.hi, "residual": r,
                            "est": self.est.get(c.mint) or {}})
        return out

    def plan(self, split: str) -> list[Unit]:
        return pack(self.items(split), target=self.target, max_scan_s=self.max_scan_s)

    def progress(self) -> dict:
        out = {}
        for s, cs in self.sel.items():
            done = sum(1 for c in cs if not self.residual(c))
            err = sum(1 for c in cs if c.mint in self.st["err"] and self.residual(c))
            units = self.plan(s) if s in self.splits else None
            out[s] = {"selected": len(cs), "fetched": done, "errors": err, "todo": len(cs) - done - err,
                      "units_left": len(units) if units is not None else None,
                      "est_bytes_left": round(sum(u.est_bytes for u in units)) if units else 0,
                      "est_trades_left": round(sum(u.est_trades for u in units)) if units else 0}
        return out

    # -- running -------------------------------------------------------------------------------------

    def run(self) -> bool:
        """Splits strictly in the given order (TRAIN before VAL before TEST). True when every requested split has
        nothing left to fetch (fetched or errored); False when stopped by the deadline / query cap."""
        for split in self.splits:
            for _pass in range(2 + TIMEOUT_TRIES):
                units = self.plan(split)
                if not units:
                    break
                log.info("b1c %s pass %d: %d units, est %.1f MB, %.0f trades, coins %d", split, _pass, len(units),
                         sum(u.est_bytes for u in units) / 1e6, sum(u.est_trades for u in units),
                         len({p[0] for u in units for p in u.pieces}))
                for u in units:
                    if not self.run_unit(split, u):
                        return False
            else:
                if self.plan(split):
                    log.warning("b1c %s: units left after %d passes", split, 2 + TIMEOUT_TRIES)
                    return False
        return True

    def run_unit(self, split: str, u: Unit) -> bool:
        """False only when stopped (deadline / query cap); errors are recorded and return True."""
        bf = self.bf
        if bf.should_stop():
            return False
        t0, t1 = u.t0, u.t1
        bf.slots.ensure(t0 - Q15, t1 + Q15)
        params = dict(s0=bf.slots.first_slot(t0), s1=bf.slots.last_slot_before((t1 - 1) // Q15 * Q15 + Q15),
                      t0=utc(t0), t1=utc(t1), min_usol=MIN_USOL)
        sql = self.render("b1c", win=self._sql_tuples([(m, p or "1", int(a), int(b)) for m, p, a, b in u.pieces]),
                          mints=self._sql_in(sorted({p[0] for p in u.pieces})), **params)
        stats = self.run_stats.setdefault(split, {})
        stats["queries"] = stats.get("queries", 0) + 1
        from cryptohouse import QueryTimeout, ResultTooLarge
        try:
            res = bf._query(sql, tag=f"b1c:{split}:{utc(t0)}:{len(u.pieces)}")
        except ResultTooLarge as e:
            halves = split_too_large(u)
            if halves is None:
                stats["errors"] = stats.get("errors", 0) + 1
                self._error(u, f"too_large: {str(e)[:160]}")
                return True
            stats["splits_large"] = stats.get("splits_large", 0) + 1
            log.warning("b1c %s %s too large (%d pieces, est %.0f kB): split", split, utc(t0), len(u.pieces),
                        u.est_bytes / 1e3)
            return all(self.run_unit(split, h) for h in halves if h.pieces)
        except QueryTimeout:
            halves = split_timeout(u)
            if halves is None:
                stats["timeouts_deferred"] = stats.get("timeouts_deferred", 0) + 1
                self._timeout(u)
                return True
            stats["splits_timeout"] = stats.get("splits_timeout", 0) + 1
            log.warning("b1c %s %s timed out (span %d s): split at a 15-min anchor", split, utc(t0), u.span)
            return all(self.run_unit(split, h) for h in halves if h.pieces)
        self._save(split, u, params, res)
        stats["units_ok"] = stats.get("units_ok", 0) + 1
        return True

    def _save(self, split: str, u: Unit, params: dict, res) -> None:
        key = u.key()
        payload = {"kind": "b1c", "split": split, "t0": u.t0, "t1": u.t1, "params": params, "pieces": u.pieces,
                   "est_bytes": round(u.est_bytes), "est_trades": round(u.est_trades, 1), "columns": res.columns,
                   "rows": res.rows, "elapsed_s": res.elapsed_s, "rows_read": res.rows_read,
                   "query_id": res.query_id, "fetched_ts": time.time()}
        self.bf.store.save_chunk("b1c", key, payload)          # the chunk first, then the state
        rows = {(d["mint"], int(d["lo"])): d for d in (dict(zip(res.columns, r)) for r in res.rows)}
        n_tr, b_tr, bad = 0, 0, []
        for m, _p, a, b in u.pieces:
            d = rows.get((m, int(a)))
            if d is not None:
                n_tr += int(d["n_trades"])
                b_tr += int(d.get("b_trades") or 0)
                if int(d.get("n_overflow") or 0) > 0 or len(d["trades"]) != int(d["n_trades"]):
                    bad.append(m)
                    self.st["err"][m] = {"msg": f"overflow {d.get('n_overflow')} / {len(d['trades'])} of "
                                                f"{d['n_trades']}", "lo": int(a), "hi": int(b), "ts": time.time()}
                    continue
            self.st["cov"][m] = merge_intervals(self.st["cov"].get(m, []) + [[int(a), int(b)]])
        self.st["units"][key] = {"split": split, "t0": u.t0, "t1": u.t1, "n_pieces": len(u.pieces),
                                 "est_bytes": round(u.est_bytes), "b_trades": b_tr, "n_trades": n_tr,
                                 "elapsed_s": res.elapsed_s, "rows_read": res.rows_read, "ts": round(time.time())}
        if bad:
            self.bf.store.state["errors"][f"b1c:{key}"] = {"msg": f"n_overflow on {len(bad)} pieces", "ts": time.time()}
        self.bf.store.save_state()
        log.info("b1c %s %s +%d min: %d pieces, %d trades, %.0f kB (est %.0f kB)", split, utc(u.t0), u.span // 60,
                 len(u.pieces), n_tr, b_tr / 1e3, u.est_bytes / 1e3)

    def _error(self, u: Unit, msg: str) -> None:
        for m, _p, a, b in u.pieces:
            self.st["err"][m] = {"msg": msg[:200], "lo": int(a), "hi": int(b), "ts": time.time()}
        self.bf.store.state["errors"][f"b1c:{u.key()}"] = {"msg": msg[:300], "ts": time.time()}
        self.bf.store.save_state()
        log.error("b1c %s: %s (%d coins marked)", utc(u.t0), msg[:120], len(u.pieces))

    def _timeout(self, u: Unit) -> None:
        for m, _p, a, b in u.pieces:
            n = int(self.st["tmo"].get(m, 0)) + 1
            self.st["tmo"][m] = n
            if n >= TIMEOUT_TRIES:
                self.st["err"][m] = {"msg": f"timeout x{n} at one anchor", "lo": int(a), "hi": int(b),
                                     "ts": time.time()}
        self.bf.store.save_state()
        log.warning("b1c %s: timeout inside one 15-min anchor (%d pieces); deferred", utc(u.t0), len(u.pieces))
        if self.backoff > 0:
            self.sleep(self.backoff)
