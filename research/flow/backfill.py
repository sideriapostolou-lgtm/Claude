"""Resumable, quota-aware CryptoHouse backfill for the wave-2 trade-flow research (PLAN 6.1).

Phases (each resumable; every query is checkpointed to disk before the next one is sent):

* **P1** graduates (CompleteEvent) + creation + curve-life + launch features (``sql/curve.sql``) and the
  B2 server-side PumpSwap aggregates (``sql/b2.sql``) for the last ``--days`` days. The census day
  (window of ``LAB/census.json``) is processed first, then whole days going back from the newest.
* **P2** the same, extended to ``--days 21`` (U_ext starts 2026-09-16).
* **P3** B3 per-(wallet, coin) position summaries (``sql/b3.sql``) for graduates already in P1/P2.
* **P4b** B1 raw non-dust trades for the lab2 S1 universe (``FLOW/b1_select.json``), packed into <= 30-minute
  time slabs (``sql/b1c.sql``, ``b1c.py``), splits strictly in the order given (TRAIN first). Separate state file
  ``state_b1.json``. (The old coin-batch **P4**, ``sql/b1.sql``, cannot pass the 95 % coverage gate and refuses to
  run.)

Run::

    python research/flow/backfill.py --phase P1 --days 7 --out $SCRATCH/flow
    python research/flow/backfill.py --phase P1 --since 2026-10-01 --until 2026-10-09 --out $SCRATCH/flow
    python research/flow/backfill.py --phase P4b --splits train,val,test --out $SCRATCH/flow [--dry-run]
    python research/flow/backfill.py --consolidate --out $SCRATCH/flow

Chunks are clock-aligned (15-minute slot anchors from ``solana.blocks``). Curve chunks are 1 hour with a
30-minute lookback for slow graduates' creation; B2 chunks are 1 chain hour aggregating every pool whose
[g, g + 180 min) window meets that hour (each chain hour is scanned once). On TIMEOUT a chunk is halved
in time; on TOO_MANY_ROWS_OR_BYTES the pool batch is halved; on QUOTA_EXCEEDED the client sleeps to the
next server interval.
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import gzip
import hashlib
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cryptohouse import CHError, CryptoHouse, QueryTimeout, ResultTooLarge, Budget, summarize_log  # noqa: E402
from decode import render_sql, sql_in, sql_tuples  # noqa: E402
import b1c  # noqa: E402
import features  # noqa: E402

log = logging.getLogger("backfill")

SCRATCH = "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad"
LAB = Path(os.environ.get("LAB_DATA", f"{SCRATCH}/lab"))
HOUR = 3600
Q15 = 900
HORIZON_S = 180 * 60          # B2 window after graduation
CURVE_LOOKBACK_S = 30 * 60    # scan this much before a curve chunk for creations of slow graduates
LAUNCH_S = 120                # launch window after creation
B2_MAX_POOLS = 260            # pools per B2 query (result-size guard; ~0.6 MB server-side at 250)
UEXT_START = 1789516800       # 2026-09-16 00:00 UTC


def utc(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def floor_to(ts: float, step: int) -> int:
    return int(ts // step) * step


def parse_utc(s: str) -> int:
    """'YYYY-MM-DD[ HH:MM[:SS]]' (UTC) or epoch seconds -> epoch seconds."""
    s = str(s).strip()
    if s.isdigit():
        return int(s)
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            return int(datetime.strptime(s, fmt).replace(tzinfo=timezone.utc).timestamp())
        except ValueError:
            continue
    raise ValueError(f"not a UTC time: {s!r}")


def atomic_write_text(path: Path, text: str) -> None:
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


# ----------------------------------------------------------------------------------------------
# storage


class Store:
    """Raw chunks under ``raw/<kind>/`` plus one state file. Two processes must never share a state file (each
    rewrites it whole and would drop the other's updates): P1-P3 use ``state.json``, P4b ``state_b1.json``."""

    def __init__(self, out: Path, state_name: str = "state.json"):
        self.out = Path(out)
        self.out.mkdir(parents=True, exist_ok=True)
        self.state_path = self.out / state_name
        self.state = json.loads(self.state_path.read_text()) if self.state_path.exists() else {}
        for k in ("curve", "b2", "b3", "raw", "slotmap", "errors"):
            self.state.setdefault(k, {})

    def save_state(self) -> None:
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state, indent=0, sort_keys=True))
        os.replace(tmp, self.state_path)

    def save_chunk(self, kind: str, key: str, payload: dict) -> Path:
        d = self.out / "raw" / kind
        d.mkdir(parents=True, exist_ok=True)
        p = d / f"{key}.json.gz"
        tmp = p.with_suffix(".tmp")
        with gzip.open(tmp, "wt") as f:
            json.dump(payload, f, separators=(",", ":"))
        os.replace(tmp, p)
        return p

    def load_chunks(self, kind: str) -> list[dict]:
        d = self.out / "raw" / kind
        if not d.exists():
            return []
        out = []
        for p in sorted(d.glob("*.json.gz")):
            with gzip.open(p, "rt") as f:
                out.append(json.load(f))
        return out


# ----------------------------------------------------------------------------------------------
# slot map


class SlotMap:
    """15-minute buckets: t -> (first slot, last slot). Bucket-aligned lookups only."""

    def __init__(self, store: Store, ch: CryptoHouse):
        self.store, self.ch = store, ch
        self.path = store.out / "slotmap.json"
        self.m: dict[int, tuple[int, int]] = {}
        if self.path.exists():
            for attempt in range(5):          # another process may be rewriting it (atomic since 2026-10-09)
                try:
                    self.m = {int(k): tuple(v) for k, v in json.loads(self.path.read_text()).items()}
                    break
                except json.JSONDecodeError:
                    if attempt == 4:
                        raise
                    time.sleep(1)

    def ensure(self, t_lo: int, t_hi: int) -> None:
        t_lo, t_hi = floor_to(t_lo, Q15), floor_to(t_hi, Q15) + Q15
        missing = [t for t in range(t_lo, t_hi, Q15) if t not in self.m]
        if not missing:
            return
        a = missing[0]
        while a <= missing[-1]:
            b = min(a + 18 * 86400, missing[-1] + Q15)
            sql = render_sql("slot_map", t0=utc(a), t1=utc(b))
            res = self.ch.query(sql, tag=f"slotmap:{utc(a)}")
            for t, lo, hi, _n in res.rows:
                self.m[int(t)] = (int(lo), int(hi))
            a = b
        atomic_write_text(self.path, json.dumps({str(k): v for k, v in sorted(self.m.items())}))

    def first_slot(self, t: int) -> int:
        return self.m[floor_to(t, Q15)][0]

    def last_slot_before(self, t: int) -> int:
        return self.m[floor_to(t, Q15) - Q15][1]

    def latest_bucket(self) -> int:
        return max(self.m) if self.m else 0


# ----------------------------------------------------------------------------------------------
# backfill


class Backfill:
    def __init__(self, out: Path, ch: CryptoHouse, deadline: float | None, max_queries: int | None,
                 state_name: str = "state.json"):
        self.store = Store(out, state_name)
        self.ch = ch
        self.slots = SlotMap(self.store, ch)
        self.deadline = deadline
        self.max_queries = max_queries
        self.n_queries = 0
        self.t_start = time.time()
        self._grads: dict[str, dict] | None = None

    # -- budget / stop ---------------------------------------------------------------------------

    def should_stop(self) -> bool:
        if self.deadline and time.time() > self.deadline:
            return True
        if self.max_queries is not None and self.n_queries >= self.max_queries:
            return True
        return False

    def _query(self, sql: str, tag: str):
        self.n_queries += 1
        return self.ch.query(sql, tag=tag)

    # -- graduates index -------------------------------------------------------------------------

    def graduates(self) -> dict[str, dict]:
        if self._grads is None:
            g: dict[str, dict] = {}
            for ch in self.store.load_chunks("curve"):
                cols = ch["columns"]
                for r in ch["rows"]:
                    d = dict(zip(cols, r))
                    old = g.get(d["mint"])
                    if old is None or (d["has_create"] and not old["has_create"]):
                        g[d["mint"]] = d
            self._grads = g
        return self._grads

    # -- curve chunks ----------------------------------------------------------------------------

    def curve_done(self, hour: int) -> bool:
        st = self.store.state["curve"].get(str(hour))
        return bool(st and st.get("done"))

    def run_curve_hour(self, hour: int) -> bool:
        st = self.store.state["curve"].setdefault(str(hour), {"parts": {}, "done": False})
        parts = st["parts"] or {f"{hour}-{hour + HOUR}": None}
        st["parts"] = parts
        for key in sorted(parts, key=lambda k: int(k.split("-")[0])):
            if parts[key] is not None:
                continue
            if self.should_stop():
                return False
            t0, t1 = (int(x) for x in key.split("-"))
            self.slots.ensure(t0 - CURVE_LOOKBACK_S - Q15, t1 + 2 * Q15)
            params = dict(
                s_lo=self.slots.first_slot(t0 - CURVE_LOOKBACK_S), s0=self.slots.first_slot(t0),
                s1=self.slots.last_slot_before(t1), s1_pool=self.slots.last_slot_before(t1 + Q15),
                t_lo=utc(t0 - CURVE_LOOKBACK_S - 120), t_hi=utc(t1 + Q15 + 120), launch_s=LAUNCH_S,
            )
            try:
                res = self._query(render_sql("curve", **params), tag=f"curve:{utc(t0)}")
            except QueryTimeout:
                if t1 - t0 <= Q15:
                    self._error("curve", key, "timeout at minimum chunk")
                    parts[key] = {"error": "timeout"}
                    continue
                mid = t0 + floor_to((t1 - t0) // 2, Q15)
                del parts[key]
                parts[f"{t0}-{mid}"] = None
                parts[f"{mid}-{t1}"] = None
                self.store.save_state()
                log.warning("curve %s timed out; split at %s", utc(t0), utc(mid))
                return self.run_curve_hour(hour)
            except ResultTooLarge as e:
                self._error("curve", key, str(e))
                parts[key] = {"error": "too_large"}
                continue
            payload = {"kind": "curve", "t0": t0, "t1": t1, "params": params, "columns": res.columns,
                       "rows": res.rows, "elapsed_s": res.elapsed_s, "rows_read": res.rows_read,
                       "query_id": res.query_id, "fetched_ts": time.time()}
            self.store.save_chunk("curve", key, payload)
            parts[key] = {"n": len(res.rows), "elapsed_s": res.elapsed_s}
            self._grads = None
            self.store.save_state()
        st["done"] = all(v is not None for v in parts.values())
        self.store.save_state()
        return st["done"]

    # -- B2 chunks -------------------------------------------------------------------------------

    def b2_ready(self, hour: int) -> bool:
        return all(self.curve_done(h) for h in range(hour - 3 * HOUR, hour + HOUR, HOUR))

    def b2_pools_for(self, hour: int) -> list[tuple[str, str, int]]:
        act = []
        for g in self.graduates().values():
            gts = int(g["g_ts"])
            if g.get("pool") and gts < hour + HOUR and gts + HORIZON_S > hour:
                act.append((g["pool"], g["mint"], gts))
        return sorted(act, key=lambda a: a[2])

    def run_b2_hour(self, hour: int) -> bool:
        st = self.store.state["b2"].setdefault(str(hour), {"done_pools": [], "parts": {}, "done": False})
        act = self.b2_pools_for(hour)
        done = set(st["done_pools"])
        todo = [a for a in act if a[0] not in done]
        while todo:
            if self.should_stop():
                return False
            batch = todo[:B2_MAX_POOLS]
            ok = self._run_b2_batch(hour, hour, hour + HOUR, batch, st)
            if not ok:
                return False
            done = set(st["done_pools"])
            todo = [a for a in act if a[0] not in done]
        st["done"] = True
        st["n_pools"] = len(act)
        self.store.save_state()
        return True

    def _run_b2_batch(self, hour: int, t0: int, t1: int, batch: list, st: dict) -> bool:
        self.slots.ensure(t0 - Q15, t1 + Q15)
        params = dict(
            s0=self.slots.first_slot(t0), s1=self.slots.last_slot_before(t1),
            t0=utc(t0), t1=utc(t1), act=sql_tuples(batch), mints=sql_in([b[1] for b in batch]),
            horizon_s=HORIZON_S,
        )
        bkey = hashlib.sha1(",".join(b[0] for b in batch).encode()).hexdigest()[:10]
        key = f"{t0}-{t1}-{bkey}"

        def split(mid: int) -> bool:
            ok = self._run_b2_part(hour, t0, mid, batch, st) and self._run_b2_part(hour, mid, t1, batch, st)
            if ok and (t0, t1) == (hour, hour + HOUR):
                self._mark_pools(st, batch)   # only the full hour marks pools done (nested splits resume)
            return ok

        if f"split:{key}" in st["parts"]:          # resumed after an earlier timeout: go straight to the halves
            return split(int(st["parts"][f"split:{key}"]))
        try:
            res = self._query(render_sql("b2", **params), tag=f"b2:{utc(t0)}:{len(batch)}")
        except QueryTimeout:
            if t1 - t0 > Q15:
                mid = t0 + floor_to((t1 - t0) // 2, Q15)
                log.warning("b2 %s timed out with %d pools; splitting time at %s", utc(t0), len(batch), utc(mid))
                st["parts"][f"split:{key}"] = mid
                self.store.save_state()
                return split(mid)
            self._error("b2", key, "timeout at minimum chunk")
            return self._mark_pools(st, batch, error="timeout")
        except ResultTooLarge:
            if len(batch) > 1:
                h = len(batch) // 2
                log.warning("b2 %s result too large with %d pools; halving", utc(t0), len(batch))
                return (self._run_b2_batch(hour, t0, t1, batch[:h], st)
                        and self._run_b2_batch(hour, t0, t1, batch[h:], st))
            self._error("b2", key, "too large for one pool")
            return self._mark_pools(st, batch, error="too_large")
        self._save_b2(key, t0, t1, params, batch, res)
        if (t0, t1) == (hour, hour + HOUR):
            self._mark_pools(st, batch)
        return True

    def _run_b2_part(self, hour: int, t0: int, t1: int, batch: list, st: dict) -> bool:
        pk = f"{t0}-{t1}-" + hashlib.sha1(",".join(b[0] for b in batch).encode()).hexdigest()[:10]
        if st["parts"].get(pk):
            return True
        if self.should_stop():
            return False
        ok = self._run_b2_batch(hour, t0, t1, batch, st)
        if ok:
            st["parts"][pk] = True
            self.store.save_state()
        return ok

    def _save_b2(self, key, t0, t1, params, batch, res) -> None:
        p = dict(params)
        p["act"] = batch
        p.pop("mints", None)
        payload = {"kind": "b2", "t0": t0, "t1": t1, "params": p, "columns": res.columns, "rows": res.rows,
                   "elapsed_s": res.elapsed_s, "rows_read": res.rows_read, "query_id": res.query_id,
                   "fetched_ts": time.time()}
        self.store.save_chunk("b2", key, payload)

    def _mark_pools(self, st: dict, batch: list, error: str | None = None) -> bool:
        st["done_pools"] = sorted(set(st["done_pools"]) | {b[0] for b in batch})
        if error:
            st.setdefault("errors", {}).update({b[0]: error for b in batch})
        self.store.save_state()
        return True

    def _error(self, kind: str, key: str, msg: str) -> None:
        self.store.state["errors"][f"{kind}:{key}"] = {"msg": msg[:300], "ts": time.time()}
        self.store.save_state()

    # -- P1/P2 driver ------------------------------------------------------------------------------

    def run_range(self, start: int, end: int, b2_end: int) -> bool:
        """Curve hours [start - 3h, end) then B2 hours [start, b2_end) as soon as each is ready."""
        log.info("range %s -> %s (b2 to %s)", utc(start), utc(end), utc(b2_end))
        for h in range(start - 3 * HOUR, end, HOUR):
            if not self.curve_done(h):
                if not self.run_curve_hour(h):
                    return False
            for hb in range(start, min(b2_end, h + HOUR), HOUR):
                if not self.store.state["b2"].get(str(hb), {}).get("done") and self.b2_ready(hb):
                    if not self.run_b2_hour(hb):
                        return False
            self.write_manifest()
        for hb in range(start, b2_end, HOUR):
            if not self.store.state["b2"].get(str(hb), {}).get("done"):
                for h in range(hb - 3 * HOUR, hb + HOUR, HOUR):
                    if not self.curve_done(h) and h < end + 3 * HOUR:
                        if not self.run_curve_hour(h):
                            return False
                if not self.run_b2_hour(hb):
                    return False
                self.write_manifest()
        return True

    def p1(self, days: float, now_limit: int, census_first: bool = True, since: int | None = None) -> None:
        """Census day first, then whole days back from the newest hour. ``start_all`` is hour-aligned (B2 and curve
        state keys are hours): ``--days 8.x`` used to produce non-aligned keys, and ``--days 7`` cannot reach
        10-01 00:00. ``since`` overrides ``days`` with an absolute start (floored to the hour)."""
        ranges = []
        if census_first:
            c = json.loads((LAB / "census.json").read_text())
            cs = floor_to(c["created_min_ts"], HOUR)
            ce = floor_to(c["census_finished_ts"], HOUR) + HOUR
            ranges.append((cs, min(ce, now_limit)))
        end = floor_to(now_limit, HOUR)
        start_all = floor_to(max(UEXT_START, since if since is not None else end - int(days * 86400)), HOUR)
        d = end
        while d > start_all:
            ranges.append((max(start_all, d - 86400), d))
            d -= 86400
        self.slots.ensure(start_all - 4 * HOUR, now_limit)
        self.store.state["ranges"] = [[a, b] for a, b in ranges]
        for a, b in ranges:
            b2_end = min(b + 3 * HOUR, floor_to(now_limit, HOUR))
            if not self.run_range(a, b, b2_end):
                log.info("stopping (deadline or query cap)")
                break
        self.write_manifest()

    # -- P3 / P4 -----------------------------------------------------------------------------------

    def run_windows(self, kind: str, sql_name: str, items: list[tuple], batch_size: int, extra: dict) -> None:
        """Generic batched per-coin-window job (B3 summaries or B1 raw trades)."""
        st = self.store.state[kind]
        todo = [it for it in items if it[0] not in st]
        log.info("%s: %d coins to do (%d done)", kind, len(todo), len(items) - len(todo))
        i = 0
        while i < len(todo) and not self.should_stop():
            batch = todo[i:i + batch_size]
            if self._run_window_batch(kind, sql_name, batch, extra):
                i += len(batch)
            self.write_manifest()

    def _run_window_batch(self, kind, sql_name, batch, extra) -> bool:
        t0 = floor_to(min(b[2] for b in batch), Q15)
        t1 = floor_to(max(b[3] for b in batch), Q15) + Q15
        self.slots.ensure(t0 - Q15, t1 + Q15)
        params = dict(s0=self.slots.first_slot(t0), s1=self.slots.last_slot_before(t1), t0=utc(t0), t1=utc(t1),
                      win=sql_tuples([(b[0], b[1] or "1", b[2], b[3]) for b in batch]),
                      mints=sql_in([b[0] for b in batch]), **extra)
        key = f"{t0}-{hashlib.sha1(','.join(b[0] for b in batch).encode()).hexdigest()[:10]}"
        try:
            res = self._query(render_sql(sql_name, **params), tag=f"{kind}:{utc(t0)}:{len(batch)}")
        except (QueryTimeout, ResultTooLarge) as e:
            if len(batch) > 1:
                h = len(batch) // 2
                return (self._run_window_batch(kind, sql_name, batch[:h], extra)
                        and self._run_window_batch(kind, sql_name, batch[h:], extra))
            self.store.state[kind][batch[0][0]] = {"error": type(e).__name__}
            self._error(kind, batch[0][0], str(e))
            return True
        p = dict(params)
        p.pop("mints", None)
        p["win"] = batch
        self.store.save_chunk(kind, key, {"kind": kind, "params": p, "columns": res.columns, "rows": res.rows,
                                          "elapsed_s": res.elapsed_s, "rows_read": res.rows_read,
                                          "query_id": res.query_id, "fetched_ts": time.time()})
        for b in batch:
            self.store.state[kind][b[0]] = {"chunk": key}
        self.store.save_state()
        return True

    def coin_windows(self, horizon_s: int, only: callable | None = None) -> list[tuple]:
        items = []
        for g in self.graduates().values():
            if only and not only(g):
                continue
            gts = int(g["g_ts"])
            lo = int(g["c_ts"]) if g.get("has_create") else gts - CURVE_LOOKBACK_S
            items.append((g["mint"], g.get("pool") or "", lo, gts + horizon_s))
        return sorted(items, key=lambda x: x[3])

    # -- manifest ------------------------------------------------------------------------------------

    def write_manifest(self) -> dict:
        grads = self.graduates()
        st = self.store.state
        curve_hours = sorted(int(h) for h, v in st["curve"].items() if v.get("done"))
        b2_hours = sorted(int(h) for h, v in st["b2"].items() if v.get("done"))
        n = len(grads)
        man = {
            "written_utc": utc(time.time()),
            "out": str(self.store.out),
            "graduates": n,
            "graduates_with_create": sum(1 for g in grads.values() if g.get("has_create")),
            "graduates_with_pool": sum(1 for g in grads.values() if g.get("pool")),
            "graduates_mayhem_flag": sum(1 for g in grads.values() if g.get("is_mayhem")),   # CreateEvent flag only
            "curve_hours_done": len(curve_hours),
            "curve_span": [utc(curve_hours[0]), utc(curve_hours[-1] + HOUR)] if curve_hours else None,
            "b2_hours_done": len(b2_hours),
            "b2_span": [utc(b2_hours[0]), utc(b2_hours[-1] + HOUR)] if b2_hours else None,
            "b3_coins": sum(1 for v in st["b3"].values() if "chunk" in v),
            "raw_coins": sum(1 for v in st["raw"].values() if "chunk" in v),
            "errors": len(st["errors"]),
            "ranges": [[utc(a), utc(b)] for a, b in st.get("ranges", [])],
            "this_run": {"queries": self.n_queries, "wall_s": round(time.time() - self.t_start)},
            "queries": summarize_log(self.ch.qlog.path),
            "quota_now": self.ch.usage(),
        }
        (self.store.out / "manifest.json").write_text(json.dumps(man, indent=1))
        return man


# ----------------------------------------------------------------------------------------------
# consolidation (offline)


@contextlib.contextmanager
def consolidate_lock(out: Path):
    """Exclusive ``flock`` on ``FLOW/consolidate.lock``: P1, P4b and manual runs all consolidate."""
    lp = Path(out) / "consolidate.lock"
    with open(lp, "a+") as lf:
        fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lf.fileno(), fcntl.LOCK_UN)


@contextlib.contextmanager
def state_lock(path: Path, wait: bool = True):
    """One process per state file (P1-P3: ``state.lock``, P4b: ``state_b1.lock``); a second one waits."""
    with open(path, "a+") as lf:
        try:
            fcntl.flock(lf.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            if not wait:
                raise
            log.warning("%s is held by another backfill process: waiting for it", path.name)
            fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lf.fileno(), fcntl.LOCK_UN)


def write_parquet(table, path: Path) -> None:
    """tmp + os.replace: a reader never sees a half-written table."""
    import pyarrow.parquet as pq

    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    pq.write_table(table, tmp, compression="zstd")
    os.replace(tmp, path)


def consolidate(out: Path) -> dict:
    """Rebuild the Parquet tables from the raw chunks (offline), under the consolidate lock."""
    with consolidate_lock(out):
        return _consolidate(Path(out))


def _consolidate(out: Path) -> dict:
    import pyarrow as pa

    store = Store(out)
    # graduates
    grads: dict[str, dict] = {}
    for ch in store.load_chunks("curve"):
        for r in ch["rows"]:
            d = dict(zip(ch["columns"], r))
            old = grads.get(d["mint"])
            if old is None or (d["has_create"] and not old["has_create"]):
                grads[d["mint"]] = d
    for d in grads.values():
        d["grad_delay_s"] = (d["g_ts"] - d["c_ts"]) if d.get("has_create") else None
        d["sol_quoted"] = d.get("pool_quote_mint") == "So11111111111111111111111111111111111111112"
        # non-SOL-quoted curves use another TradeEvent/CreateEvent tail: their rsol and curve_quote_mint are not
        # valid, so the "real SOL < 80 at completion" rule applies to SOL-quoted coins only
        d["mayhem"] = bool(d.get("is_mayhem")) or (d["sol_quoted"] and (d.get("rsol_complete") or 0) < 80)
        if not d.get("has_create"):
            # creation outside the scan: launch / bundle / sniper / creator features were never observed. They read 0
            # in the raw rows; make them NULL so they cannot be mistaken for real zeros (audit: 7 % of tradeable,
            # 17 % of non-instant tradeable graduates on the pilot). Curve-life totals are partial: flag them.
            for k in list(d):
                if k.startswith(("l_", "z_", "sn60_", "creator_", "first20_")):
                    d[k] = None
            d["curve_partial"] = True
        else:
            d["curve_partial"] = False
    if grads:
        write_parquet(pa.Table.from_pylist(sorted(grads.values(), key=lambda d: d["g_ts"])), out / "graduates.parquet")
    # B2: merge per pool
    per_pool: dict[str, list] = {}
    for ch in store.load_chunks("b2"):
        for r in ch["rows"]:
            d = dict(zip(ch["columns"], r))
            per_pool.setdefault(d["pool"], []).append(d)
    bars_rows, coin_rows = [], []
    for pool, rows in per_pool.items():
        m = features.merge_b2(rows)
        agent = m.pop("agent")
        a_by_min = features.agent_sol_by_minute(agent)
        for b in m.pop("bars"):
            gq = grads.get(m["mint"], {})
            b.update({"mint": m["mint"], "pool": pool, "g_ts": m["g_ts"],
                      "sol_quoted": gq.get("sol_quoted"), "mayhem": gq.get("mayhem"),   # non-SOL pools: prices/flows in quote units
                      "minute_idx": (b["minute_ts"] - (m["g_ts"] // 60) * 60) // 60,
                      "agent_buy_sol": a_by_min.get(b["minute_ts"], 0.0)})
            b.setdefault("price_repaired", 0)
            bars_rows.append(b)
        g = grads.get(m["mint"], {})
        excl = agent["wallet"] if agent else None
        m.update({
            "agent_present": agent is not None,
            "agent_wallet": agent["wallet"] if agent else None,
            "agent_slices": agent["n_slices"] if agent else 0,
            "agent_sol": agent["sol"] if agent else 0.0,
            "agent_median_gap": agent["median_gap"] if agent else None,
            "agent_gap_cv": agent["gap_cv"] if agent else None,
            "agent_gap_band_share": agent["gap_band_share"] if agent else None,
            "agent_first_offset_s": agent["first_offset_s"] if agent else None,
            "agent_known_at": agent["known_at"] if agent else None,
            "w120_top5_share_ex_agent": features.top_share(m.get("w120_top10"), m.get("w120_buy_sol"), 5, excl),
            "w120_top10": json.dumps(m.get("w120_top10")), "w300_top10": json.dumps(m.get("w300_top10")),
            "grad_delay_s": g.get("grad_delay_s"),
            "sol_quoted": g.get("sol_quoted"), "mayhem": g.get("mayhem"),
            "virt_known": bool(m.get("virt_sol")),   # False: prices are x / y without the virtual reserve (~17 % low)
        })
        coin_rows.append(m)
    if bars_rows:
        write_parquet(pa.Table.from_pylist(bars_rows), out / "b2_bars.parquet")
    if coin_rows:
        write_parquet(pa.Table.from_pylist(coin_rows), out / "b2_coins.parquet")
    # B3 wallets (long format)
    wrows = []
    wf = ("wallet_h", "wallet", "n_buys", "n_sells", "buy_sol", "sell_sol", "buy_tok", "sell_tok", "curve_buy_sol",
          "curve_sell_sol", "first_ts", "last_ts", "first_buy_ts", "last_sell_ts", "peak_tok", "end_tok",
          "orphan_tok", "n_sell_without_holding")
    for ch in store.load_chunks("b3"):
        for r in ch["rows"]:
            d = dict(zip(ch["columns"], r))
            for w in d["wallets"]:
                row = dict(zip(wf, w))
                row["mint"] = d["mint"]
                wrows.append(row)
    if wrows:
        write_parquet(pa.Table.from_pylist(wrows), out / "b3_positions.parquet")
    # B1 raw trades (P4b, compact tuples from sql/b1c.sql): complete coins only
    b1sum = consolidate_b1(out, grads, bars_rows)
    summary = {"graduates": len(grads), "b2_coins": len(coin_rows), "b2_bars": len(bars_rows),
               "b3_positions": len(wrows), **b1sum}
    log.info("consolidated: %s", summary)
    return summary


B1_SCHEMA = (("slot", "int64"), ("tx_idx", "int64"), ("pix", "int64"), ("ix", "int64"), ("ts", "int64"),
             ("venue", "int64"), ("is_buy", "int64"), ("wallet_h", "uint64"), ("usol", "int64"), ("tok", "int64"),
             ("x0", "int64"), ("y0", "int64"), ("fees", "int64"), ("virt_ksol", "int64"), ("mint", "string"),
             ("src", "int64"))


def consolidate_b1(out: Path, grads: dict, bars_rows: list) -> dict:
    """``raw/b1c`` -> ``b1_trades.parquet`` (complete coins only, same schema as before), ``b1_coins.parquet``
    (every fetched or selected coin: pieces, complete, B1 = B2 gate) and ``b1_manifest.json`` (per split)."""
    import pyarrow as pa

    if not (out / "raw" / "b1c").exists():
        return {"b1_trades": 0}
    pool_nd: dict[str, dict[int, float]] = {}
    for b in bars_rows:
        d = pool_nd.setdefault(b["pool"], {})
        d[int(b["minute_ts"])] = d.get(int(b["minute_ts"]), 0.0) + float(
            (b.get("n_buys") or 0) + (b.get("n_sells") or 0) - (b.get("n_dust") or 0))
    sel_p = out / "b1_select.json"
    selection = b1c.load_selection(sel_p) if sel_p.exists() else None
    res = b1c.consolidate_b1(out, grads, pool_nd, selection)
    tr = res["trades"]
    stale = out / "wallet_dict.parquet"     # P4 only; P4b keeps no dictionary (S1/D1 hash pooled accounts)
    if tr is not None:
        schema = pa.schema([(k, getattr(pa, t)()) for k, t in B1_SCHEMA])
        write_parquet(pa.Table.from_arrays([pa.array(tr[k], type=schema.field(k).type) for k, _ in B1_SCHEMA],
                                           schema=schema), out / "b1_trades.parquet")
        if stale.exists():
            stale.unlink()
    elif (out / "b1_trades.parquet").exists():
        (out / "b1_trades.parquet").unlink()      # no complete coin: never leave an older table behind
    if res["coins"]:
        write_parquet(pa.Table.from_pylist(res["coins"]), out / "b1_coins.parquet")
    man = {"written_utc": utc(time.time()), "rule": "complete = fetched pieces cover [c_ts, g_ts + 7200); only "
           "complete coins are in b1_trades.parquet; gate = B1 pool trades per minute vs B2 non-dust (flag > 0.5 %)",
           "selection": str(sel_p) if selection is not None else None,
           "selection_written_utc": (json.loads(sel_p.read_text()).get("written_utc") if selection is not None else None),
           "summary": res["summary"], "splits": res["manifest"]}
    atomic_write_text(out / "b1_manifest.json", json.dumps(man, indent=1))
    return res["summary"]


# ----------------------------------------------------------------------------------------------


def run_p4b(bf: "Backfill", out: Path, splits: list[str], target: float, max_scan_s: int, retry_errors: bool,
            dry_run: bool, selection_path: Path | None = None) -> dict:
    """P4b: B1 for the S1 universe of ``splits`` (in that order), from ``FLOW/b1_select.json``."""
    import pandas as pd

    sel_p = Path(selection_path or out / "b1_select.json")
    if not sel_p.exists():
        raise SystemExit(f"{sel_p} missing: run `python research/lab2/b1_select.py` after consolidating")
    doc = json.loads(sel_p.read_text())
    sel = b1c.load_selection(sel_p)
    unknown = [s for s in splits if s not in sel]
    if unknown:
        raise SystemExit(f"splits {unknown} not in {sel_p} (has {sorted(sel)})")
    snap = (doc.get("snapshot") or {}).get("graduates.parquet_mtime")
    gp = out / "graduates.parquet"
    if snap is not None and gp.exists() and gp.stat().st_mtime > float(snap) + 1:
        log.warning("b1_select.json predates graduates.parquet (re-run research/lab2/b1_select.py): newly usable "
                    "coins are not selected yet")
    coins = [c for s in splits for c in sel[s]]
    g = pd.read_parquet(gp, columns=["mint", "g_ts", "c_ts", "curve_n_buys", "curve_n_sells", "l_n_buys", "l_n_sells"])
    b = pd.read_parquet(out / "b2_bars.parquet", columns=["mint", "minute_ts", "n_buys", "n_sells", "n_dust"])
    est = b1c.estimates_from_frames(coins, g, b)
    runner = b1c.Runner(bf, sel, splits, est, target=target, max_scan_s=max_scan_s, retry_errors=retry_errors)
    before = runner.progress()
    report = {"written_utc": utc(time.time()), "splits_order": splits, "dry_run": dry_run, "before": before}
    if dry_run:
        for s in splits:
            units = runner.plan(s)
            spans = [u.span for u in units]
            report.setdefault("plan", {})[s] = {
                "units": len(units), "est_mb": round(sum(u.est_bytes for u in units) / 1e6, 2),
                "est_trades": round(sum(u.est_trades for u in units)),
                "mean_fill_kb": round(sum(u.est_bytes for u in units) / max(len(units), 1) / 1e3, 1),
                "mean_span_min": round(sum(spans) / max(len(spans), 1) / 60, 1),
                "first_utc": utc(min(u.t0 for u in units)) if units else None,
                "last_utc": utc(max(u.t1 for u in units)) if units else None}
        print(json.dumps(report, indent=1))
        return report
    try:
        report["finished"] = runner.run()
    finally:
        report["after"] = runner.progress()
        report["run"] = runner.run_stats
        report["queries_this_run"] = bf.n_queries
        atomic_write_text(out / "b1_progress.json", json.dumps(report, indent=1))
    return report


def discovery_gaps(state: dict, since: int, until: int) -> dict:
    """Curve hours of [since - 3 h, until) and B2 hours of [since, until) not done yet (P1 discovery coverage)."""
    s, u = floor_to(since, HOUR), floor_to(until, HOUR)
    cur = [utc(h) for h in range(s - 3 * HOUR, u, HOUR) if not (state.get("curve", {}).get(str(h)) or {}).get("done")]
    b2 = [utc(h) for h in range(s, u, HOUR) if not (state.get("b2", {}).get(str(h)) or {}).get("done")]
    return {"since": utc(s), "until": utc(u), "curve": cur, "b2": b2}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--phase", choices=["P1", "P2", "P3", "P4", "P4b"])
    ap.add_argument("--days", type=float, default=7)
    ap.add_argument("--since", default=None, help="P1/P2: absolute start (UTC 'YYYY-MM-DD[ HH:MM]'), overrides --days")
    ap.add_argument("--until", default=None, help="P1/P2: do not scan past this UTC time (skips hours outside every "
                                                  "split); default: now - 45 min")
    ap.add_argument("--out", default=f"{SCRATCH}/flow")
    ap.add_argument("--max-minutes", type=float, default=None, help="stop after this much wall time")
    ap.add_argument("--max-queries", type=int, default=None, help="stop after this many queries in this run")
    ap.add_argument("--max-per-hour", type=int, default=90)
    ap.add_argument("--no-census-first", action="store_true")
    ap.add_argument("--consolidate", action="store_true", help="build Parquet tables from raw chunks (offline)")
    ap.add_argument("--no-consolidate", action="store_true", help="skip the consolidation at the end of a phase")
    ap.add_argument("--b3-batch", type=int, default=12)
    ap.add_argument("--b3-horizon-min", type=int, default=60, help="B3 window = [created, g + this]")
    ap.add_argument("--splits", default="train,val,test", help="P4b: splits in priority order (TRAIN first)")
    ap.add_argument("--target-bytes", type=float, default=b1c.TARGET_BYTES, help="P4b: packed result size per query")
    ap.add_argument("--max-scan-min", type=int, default=b1c.MAX_SCAN_S // 60, help="P4b: slab length cap")
    ap.add_argument("--selection", default=None, help="P4b: b1_select.json (default FLOW/b1_select.json)")
    ap.add_argument("--retry-errors", action="store_true", help="P4b: retry coins marked as errors")
    ap.add_argument("--dry-run", action="store_true", help="P4b: print the packing plan, send no query")
    ap.add_argument("--check-discovery", action="store_true",
                    help="offline: exit 0 when every curve hour of [since - 3 h, until) and B2 hour of [since, until) "
                         "is done in state.json, else 1 (prints the gaps)")
    args = ap.parse_args(argv)
    if args.check_discovery:
        gaps = discovery_gaps(Store(Path(args.out)).state, parse_utc(args.since or "2026-10-01"),
                              parse_utc(args.until or utc(time.time() - 45 * 60)))
        print(json.dumps(gaps))
        return 0 if not gaps["curve"] and not gaps["b2"] else 1

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler(out / "backfill.log")])
    if args.consolidate and not args.phase:
        print(json.dumps(consolidate(out), indent=1))
        return 0
    if args.phase == "P4":
        log.error("P4 (sql/b1.sql coin batches) cannot reach the 95 %% B1 coverage gate (timeouts, coins > 1 MB): "
                  "use --phase P4b")
        return 2
    p4b = args.phase == "P4b"
    lock = contextlib.nullcontext() if (p4b and args.dry_run) else \
        state_lock(out / ("state_b1.lock" if p4b else "state.lock"))
    with lock:
        rc = _run_phase(args, out, p4b)
    if rc is not None:
        return rc
    if args.phase and not args.no_consolidate:
        consolidate(out)
    return 0


def _run_phase(args, out: Path, p4b: bool) -> int | None:
    ch = CryptoHouse(log_path=os.environ.get("CH_QUERY_LOG", str(out / "ch_query_log.jsonl")),
                     budget=Budget(max_per_hour=args.max_per_hour))
    deadline = time.time() + args.max_minutes * 60 if args.max_minutes else None
    bf = Backfill(out, ch, deadline, args.max_queries, state_name="state_b1.json" if p4b else "state.json")
    now_limit = floor_to(time.time() - 45 * 60, Q15)   # CryptoHouse lags real time by minutes
    if args.until:
        now_limit = min(now_limit, floor_to(parse_utc(args.until), Q15))
    try:
        if args.phase in ("P1", "P2"):
            days = args.days if args.phase == "P1" else max(args.days, 21)
            bf.p1(days, now_limit, census_first=not args.no_census_first,
                  since=parse_utc(args.since) if args.since else None)
        elif args.phase == "P3":
            bf.run_windows("b3", "b3", bf.coin_windows(args.b3_horizon_min * 60), args.b3_batch,
                           {"min_wallet_usol": 50_000_000})
        elif p4b:
            splits = [s.strip() for s in args.splits.split(",") if s.strip()]
            rep = run_p4b(bf, out, splits, args.target_bytes, args.max_scan_min * 60, args.retry_errors,
                          args.dry_run, Path(args.selection) if args.selection else None)
            if args.dry_run:
                return 0
            log.info("P4b finished=%s queries(run)=%s after=%s", rep.get("finished"), bf.n_queries,
                     json.dumps(rep.get("after")))
    except CHError as e:
        log.error("stopped on server error: %s", e)
    finally:
        if not p4b:
            man = bf.write_manifest()
            log.info("manifest: graduates=%s curve_hours=%s b2_hours=%s queries(run)=%s",
                     man["graduates"], man["curve_hours_done"], man["b2_hours_done"], man["this_run"]["queries"])
    return None


if __name__ == "__main__":
    sys.exit(main())
