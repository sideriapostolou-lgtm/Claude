"""Quota-aware client for CryptoHouse, the free public ClickHouse run by Goldsky and ClickHouse.

Endpoint: ``POST https://crypto-clickhouse.clickhouse.com/?user=crypto`` (empty password, readonly).

Server limits (user ``crypto``, read from ``SHOW QUOTA`` and ``system.settings`` on 2026-10-08):

* per query: 60 s, 2,000 result rows (overflow throws), 1 MB result, readonly=1 (settings are fixed);
* per client IP per hour: 120 queries, 6,000 s of execution, 3e12 rows read.

The IP is this environment's egress proxy and may be shared with other sessions, so this client
keeps well below the server quota:

* at most ``max_per_hour`` queries (default 90) in any rolling 3,600 s window and at most
  ``max_exec_s_per_hour`` seconds of execution (default 4,500);
* a persisted JSONL query log, so a restarted process respects the hour budget;
* an ``flock`` around every request, so only one query is in flight per machine;
* error-specific handling: ``QUOTA_EXCEEDED`` sleeps to the end of the server interval and retries,
  network and 5xx errors back off exponentially, while ``TIMEOUT_EXCEEDED`` and
  ``TOO_MANY_ROWS_OR_BYTES`` are raised as :class:`QueryTimeout` and :class:`ResultTooLarge` so the
  caller can halve its window or batch (see ``backfill.py``).

Results are requested as ``JSONCompact`` and 64-bit integers (sent as strings) are converted back to
``int`` using the column types.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import requests

URL = "https://crypto-clickhouse.clickhouse.com/"
USER = "crypto"
DEFAULT_LOG = os.environ.get(
    "CH_QUERY_LOG",
    "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/flow/ch_query_log.jsonl",
)

# ClickHouse error codes we treat specially.
CODE_TIMEOUT = 159            # TIMEOUT_EXCEEDED
CODE_TOO_SLOW = 160           # TOO_SLOW (estimated execution time too long)
CODE_TOO_MANY_ROWS = 158      # TOO_MANY_ROWS
CODE_QUOTA = 201              # QUOTA_EXCEEDED
CODE_SIMULTANEOUS = 202       # TOO_MANY_SIMULTANEOUS_QUERIES
CODE_MEMORY = 241             # MEMORY_LIMIT_EXCEEDED
CODE_TOO_MANY_BYTES = 307     # TOO_MANY_BYTES
CODE_ROWS_OR_BYTES = 396      # TOO_MANY_ROWS_OR_BYTES

log = logging.getLogger("cryptohouse")


class CHError(RuntimeError):
    def __init__(self, code: int | None, message: str):
        super().__init__(f"[{code}] {message[:600]}")
        self.code = code
        self.message = message


class QuotaExceeded(CHError):
    def __init__(self, code: int | None, message: str, reset_at: float):
        super().__init__(code, message)
        self.reset_at = reset_at


class QueryTimeout(CHError):
    """The query hit the 60 s limit (or the server predicted it would). Halve the window."""


class ResultTooLarge(CHError):
    """The result exceeded 2,000 rows or 1 MB, or memory. Halve the batch."""


class TransientError(CHError):
    """Network, proxy or 5xx failure that survived all retries."""


@dataclass
class Result:
    columns: list[str]
    types: list[str]
    rows: list[list[Any]]
    elapsed_s: float
    rows_read: int
    bytes_read: int
    wall_s: float
    query_id: str = ""

    def dicts(self) -> list[dict[str, Any]]:
        return [dict(zip(self.columns, r)) for r in self.rows]

    def __len__(self) -> int:
        return len(self.rows)


@dataclass
class Budget:
    max_per_hour: int = 90
    max_exec_s_per_hour: float = 4500.0
    min_gap_s: float = 1.0


# ----------------------------------------------------------------------------------------------
# value conversion


_INT_TYPE = re.compile(r"^(Nullable\()?(U?Int(8|16|32|64|128|256))\)?$")


def _convert(value: Any, ch_type: str) -> Any:
    """Convert a JSONCompact value to Python using its ClickHouse type (64-bit ints come quoted)."""
    if value is None:
        return None
    t = ch_type
    if t.startswith("LowCardinality("):
        t = t[len("LowCardinality("):-1]
    if t.startswith("Nullable("):
        t = t[len("Nullable("):-1]
    if t.startswith("Array("):
        inner = t[len("Array("):-1]
        return [_convert(v, inner) for v in value]
    if t.startswith("Tuple("):
        inner_types = _split_types(t[len("Tuple("):-1])
        return [_convert(v, it) for v, it in zip(value, inner_types)]
    if _INT_TYPE.match(t):
        return int(value)
    if t.startswith("Float") or t.startswith("Decimal"):
        if isinstance(value, str):
            v = value.lower()
            if v in ("nan", "-nan"):
                return float("nan")
            if v in ("inf", "+inf"):
                return float("inf")
            if v == "-inf":
                return float("-inf")
            return float(value)
        return float(value)
    return value


def _split_types(s: str) -> list[str]:
    """Split 'UInt64, Array(Float64), Tuple(a UInt8, b String)' at top-level commas.

    Named tuple elements ('name Type') are reduced to their type.
    """
    out, depth, cur = [], 0, []
    for ch in s:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            out.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    if cur:
        out.append("".join(cur).strip())
    res = []
    for part in out:
        # named element: "name Type(...)" -> "Type(...)"
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s+(.+)$", part)
        if m and not part.startswith(("Array(", "Tuple(", "Nullable(", "LowCardinality(")):
            res.append(m.group(2))
        else:
            res.append(part)
    return res


def parse_json_compact(text: str) -> tuple[list[str], list[str], list[list[Any]], dict]:
    doc = json.loads(text)
    meta = doc.get("meta", [])
    cols = [m["name"] for m in meta]
    types = [m["type"] for m in meta]
    rows = [[_convert(v, t) for v, t in zip(r, types)] for r in doc.get("data", [])]
    return cols, types, rows, doc.get("statistics", {})


# ----------------------------------------------------------------------------------------------
# errors


_CODE_RE = re.compile(r"Code:\s*(\d+)")
_RESET_RE = re.compile(r"[Ii]nterval will end at (\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)")


def parse_error(status: int, headers: dict, body: str, now: float | None = None) -> CHError:
    """Map a ClickHouse HTTP error response to a typed exception."""
    code = None
    h = headers.get("X-ClickHouse-Exception-Code") or headers.get("x-clickhouse-exception-code")
    if h and str(h).isdigit():
        code = int(h)
    else:
        m = _CODE_RE.search(body or "")
        if m:
            code = int(m.group(1))
    msg = (body or "").strip()
    now = time.time() if now is None else now
    if code == CODE_QUOTA or "QUOTA_EXCEEDED" in msg or "QUOTA_EXPIRED" in msg:
        reset_at = None
        m = _RESET_RE.search(msg)
        if m:
            reset_at = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp()
        if reset_at is None or reset_at < now:
            reset_at = (int(now // 3600) + 1) * 3600.0  # top of the next hour
        return QuotaExceeded(code, msg, reset_at)
    if code in (CODE_TIMEOUT, CODE_TOO_SLOW) or "TIMEOUT_EXCEEDED" in msg:
        return QueryTimeout(code, msg)
    if code in (CODE_ROWS_OR_BYTES, CODE_TOO_MANY_ROWS, CODE_TOO_MANY_BYTES, CODE_MEMORY) or \
            "TOO_MANY_ROWS_OR_BYTES" in msg:
        return ResultTooLarge(code, msg)
    if status >= 500 and code is None:
        return TransientError(code, f"HTTP {status}: {msg}")
    if code == CODE_SIMULTANEOUS:
        return TransientError(code, msg)
    return CHError(code, msg)


# ----------------------------------------------------------------------------------------------
# persisted query log


class QueryLog:
    """Append-only JSONL of every request sent (success or error); the source of truth for budgets."""

    def __init__(self, path: str | os.PathLike):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock_path = self.path.with_suffix(self.path.suffix + ".lock")

    def entries(self, since: float = 0.0) -> list[dict]:
        if not self.path.exists():
            return []
        out = []
        with open(self.path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if e.get("ts", 0) >= since:
                    out.append(e)
        return out

    def append(self, entry: dict) -> None:
        with open(self.path, "a") as f:
            f.write(json.dumps(entry, separators=(",", ":")) + "\n")
            f.flush()
            os.fsync(f.fileno())

    def window_usage(self, now: float, window_s: float = 3600.0) -> tuple[int, float, float | None]:
        """(queries, execution seconds, oldest ts) sent in (now - window_s, now]."""
        es = self.entries(since=now - window_s)
        n = len(es)
        ex = sum(float(e.get("elapsed_s") or e.get("wall_s") or 0.0) for e in es)
        oldest = min((e["ts"] for e in es), default=None)
        return n, ex, oldest

    @contextlib.contextmanager
    def exclusive(self):
        with open(self.lock_path, "a+") as lf:
            fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lf.fileno(), fcntl.LOCK_UN)


# ----------------------------------------------------------------------------------------------
# client


class CryptoHouse:
    def __init__(
        self,
        log_path: str | os.PathLike = DEFAULT_LOG,
        budget: Budget | None = None,
        http_timeout_s: float = 90.0,
        max_transient_retries: int = 4,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.time,
        wait_on_quota: bool = True,
        max_quota_waits: int = 3,
    ):
        self.qlog = QueryLog(log_path)
        self.budget = budget or Budget()
        self.http_timeout_s = http_timeout_s
        self.max_transient_retries = max_transient_retries
        self.session = session or requests.Session()
        self.sleep = sleep
        self.clock = clock
        self.wait_on_quota = wait_on_quota
        self.max_quota_waits = max_quota_waits
        self.server_reset_at: float | None = None  # set after a QUOTA_EXCEEDED

    # -- budget ---------------------------------------------------------------------------------

    def wait_for_budget(self) -> float:
        """Block until one more query fits in the rolling-hour budget. Returns seconds slept."""
        slept = 0.0
        while True:
            now = self.clock()
            if self.server_reset_at and now < self.server_reset_at:
                d = self.server_reset_at - now + 5
                log.warning("server quota exhausted; sleeping %.0f s to the interval end", d)
                self.sleep(d)
                slept += d
                continue
            es = self.qlog.entries(since=now - 3600)
            n = len(es)
            ex = sum(float(e.get("elapsed_s") or e.get("wall_s") or 0.0) for e in es)
            last = max((e["ts"] + float(e.get("wall_s") or 0) for e in es), default=0.0)
            waits = []
            if n >= self.budget.max_per_hour:
                # wait until the oldest entry that keeps us at the cap falls out of the window
                ts_sorted = sorted(e["ts"] for e in es)
                waits.append(ts_sorted[n - self.budget.max_per_hour] + 3600 - now + 1)
            if ex >= self.budget.max_exec_s_per_hour:
                acc, target = 0.0, ex - self.budget.max_exec_s_per_hour
                for e in sorted(es, key=lambda e: e["ts"]):
                    acc += float(e.get("elapsed_s") or e.get("wall_s") or 0.0)
                    if acc >= target:
                        waits.append(e["ts"] + 3600 - now + 1)
                        break
            if now - last < self.budget.min_gap_s:
                waits.append(self.budget.min_gap_s - (now - last))
            if not waits:
                return slept
            d = max(waits)
            if d > 30:
                log.info("budget: %d queries / %.0f s exec in the last hour; sleeping %.0f s", n, ex, d)
            self.sleep(d)
            slept += d

    def usage(self) -> dict:
        now = self.clock()
        n, ex, _ = self.qlog.window_usage(now)
        return {"queries_last_hour": n, "exec_s_last_hour": round(ex, 1),
                "max_per_hour": self.budget.max_per_hour}

    # -- request --------------------------------------------------------------------------------

    def _post(self, sql: str) -> requests.Response:
        return self.session.post(
            URL, params={"user": USER}, data=sql.encode("utf-8"), timeout=self.http_timeout_s,
            headers={"Content-Type": "text/plain; charset=utf-8"},
        )

    def query(self, sql: str, tag: str = "", fmt: str = "JSONCompact") -> Result:
        """Run one query under the budget. Raises QueryTimeout / ResultTooLarge / CHError."""
        sql = sql.strip().rstrip(";")
        if not re.search(r"\bFORMAT\s+\w+\s*$", sql, flags=re.I):
            sql = f"{sql}\nFORMAT {fmt}"
        transient = 0
        quota_waits = 0
        while True:
            with self.qlog.exclusive():
                self.wait_for_budget()
                t0 = self.clock()
                entry: dict[str, Any] = {"ts": round(t0, 3), "tag": tag, "sql_len": len(sql)}
                try:
                    resp = self._post(sql)
                    wall = self.clock() - t0
                    entry["wall_s"] = round(wall, 3)
                    entry["http"] = resp.status_code
                    summary = resp.headers.get("X-ClickHouse-Summary")
                    if summary:
                        try:
                            s = json.loads(summary)
                            entry["elapsed_s"] = round(int(s.get("elapsed_ns", 0)) / 1e9, 3)
                            entry["rows_read"] = int(s.get("read_rows", 0))
                            entry["bytes_read"] = int(s.get("read_bytes", 0))
                        except (ValueError, TypeError):
                            pass
                    entry["query_id"] = resp.headers.get("X-ClickHouse-Query-Id", "")
                    if resp.status_code != 200 or resp.headers.get("X-ClickHouse-Exception-Code"):
                        err = parse_error(resp.status_code, dict(resp.headers), resp.text, now=self.clock())
                        entry["error_code"] = err.code
                        entry["error"] = type(err).__name__
                        if "elapsed_s" not in entry:
                            entry["elapsed_s"] = round(wall, 3)
                        self.qlog.append(entry)
                        raise err
                    text = resp.text
                    if fmt.upper().startswith("JSONCOMPACT"):
                        cols, types, rows, stats = parse_json_compact(text)
                        elapsed = float(stats.get("elapsed", entry.get("elapsed_s", wall)))
                        rows_read = int(stats.get("rows_read", entry.get("rows_read", 0)))
                        bytes_read = int(stats.get("bytes_read", entry.get("bytes_read", 0)))
                    else:
                        cols, types, rows = [], [], [line.split("\t") for line in text.splitlines()]
                        elapsed = entry.get("elapsed_s", wall)
                        rows_read = entry.get("rows_read", 0)
                        bytes_read = entry.get("bytes_read", 0)
                    entry.update({"elapsed_s": round(elapsed, 3), "rows_read": rows_read,
                                  "bytes_read": bytes_read, "result_rows": len(rows),
                                  "result_bytes": len(text)})
                    self.qlog.append(entry)
                    log.info("ch %-28s %5.1fs exec %5.1fs wall %6.1fM rows read %4d rows out",
                             tag[:28], elapsed, wall, rows_read / 1e6, len(rows))
                    return Result(cols, types, rows, elapsed, rows_read, bytes_read, wall,
                                  entry.get("query_id", ""))
                except (requests.ConnectionError, requests.Timeout, requests.exceptions.ChunkedEncodingError) as e:
                    entry["wall_s"] = round(self.clock() - t0, 3)
                    entry["error"] = type(e).__name__
                    self.qlog.append(entry)
                    err: CHError = TransientError(None, str(e))
                except TransientError as e:
                    err = e
                except QuotaExceeded as e:
                    err = e
            # outside the lock: decide on retry
            if isinstance(err, QuotaExceeded):
                self.server_reset_at = err.reset_at
                quota_waits += 1
                if not self.wait_on_quota or quota_waits > self.max_quota_waits:
                    raise err
                log.warning("QUOTA_EXCEEDED; next interval at %s",
                            datetime.fromtimestamp(err.reset_at, timezone.utc).isoformat())
                continue  # wait_for_budget() sleeps to server_reset_at
            transient += 1
            if transient > self.max_transient_retries:
                raise err
            d = min(120.0, 5.0 * 2 ** (transient - 1))
            log.warning("transient error (%s); retry %d in %.0f s", err, transient, d)
            self.sleep(d)

    def quota_status(self) -> list[dict]:
        """Server-side view of this IP's quota (costs one query)."""
        r = self.query("SELECT * FROM system.quota_usage", tag="quota_status")
        return r.dicts()


def summarize_log(path: str | os.PathLike = DEFAULT_LOG, since: float = 0.0) -> dict:
    """Aggregate stats over the persisted query log (for manifests and reports)."""
    es = QueryLog(path).entries(since=since)
    ok = [e for e in es if not e.get("error")]
    errs: dict[str, int] = {}
    for e in es:
        if e.get("error"):
            errs[e["error"]] = errs.get(e["error"], 0) + 1
    el = sorted(float(e.get("elapsed_s", 0)) for e in ok)
    by_tag: dict[str, dict] = {}
    for e in es:
        t = (e.get("tag") or "").split(":")[0]
        d = by_tag.setdefault(t, {"n": 0, "exec_s": 0.0, "errors": 0, "rows_read": 0})
        d["n"] += 1
        d["exec_s"] = round(d["exec_s"] + float(e.get("elapsed_s") or e.get("wall_s") or 0), 1)
        d["rows_read"] += int(e.get("rows_read") or 0)
        d["errors"] += 1 if e.get("error") else 0
    return {
        "queries": len(es), "ok": len(ok), "errors": errs,
        "exec_s_total": round(sum(float(e.get("elapsed_s") or 0) for e in es), 1),
        "exec_s_median": el[len(el) // 2] if el else None,
        "exec_s_p90": el[int(len(el) * 0.9)] if el else None,
        "rows_read_total": sum(int(e.get("rows_read") or 0) for e in es),
        "first_ts": min((e["ts"] for e in es), default=None),
        "last_ts": max((e["ts"] for e in es), default=None),
        "by_tag": by_tag,
    }


if __name__ == "__main__":  # tiny CLI: python cryptohouse.py "SELECT 1"
    import sys

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ch = CryptoHouse()
    if len(sys.argv) > 1 and sys.argv[1] == "--usage":
        print(json.dumps({"local": ch.usage(), "log": summarize_log()}, indent=1))
        sys.exit(0)
    sql = sys.argv[1] if len(sys.argv) > 1 else sys.stdin.read()
    res = ch.query(sql, tag="cli")
    print("\t".join(res.columns))
    for r in res.rows:
        print("\t".join(json.dumps(v) if isinstance(v, (list, dict)) else str(v) for v in r))
    print(f"# {len(res)} rows, {res.elapsed_s:.2f}s exec, {res.rows_read/1e6:.1f}M rows read", file=sys.stderr)
