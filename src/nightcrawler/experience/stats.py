"""Pure statistics of experience (docs/EXPERIENCE.md §4.7, §5.1, §6.5). Standard library plus ``learn.evidence``.

* **Error budget** - :func:`alpha_v`: version v of a member may spend ``0.02 / (v (v + 1))`` (version 1: 0.01, the
  "99 % check"), so a member's versions together spend at most 0.02: at most 1 % lifetime chance of a false
  "Skill shown" and 1 % of a false "Worse than chance". :func:`alpha_ledger` is the fold over RECEIPTED
  ``member_version`` and ``skill_claim`` outbox rows (first row per idempotency key, :func:`first_per_key`).
* **Day blocks** - :func:`day_blocks`: consecutive judged UTC days merged until a block holds ``min_units`` units
  (counts only, never outcomes); within a block no operator keeps more than ``CLUSTER_MAX_SHARE`` of the units, the
  excess dropped in hash order. Only CLOSED blocks are returned: a block never changes once it is closed, so the
  sequence of blocks is prefix-stable and the e-processes over it are valid.
* **Bands** - :func:`band`: the always-valid two-sided band, ``learn.evidence.lower_bound`` at alpha / 2 applied to y
  and to -y (y in [-1, 1], one value per block). :func:`chance_label` / :func:`bar_label` apply §5.1's label order
  with the stability veto (:func:`stable`). :func:`rough_range` is the 95 % block bootstrap of secondary metrics.
* **Lessons** - :func:`ebh`: e-BH at level q over the e-values of the groups examined.
* **Independent situations (G53)** - :func:`icc`, :func:`n_eff` and :func:`independent_situations` (forward rows
  only, never before 15 forward days).
"""

from __future__ import annotations

import hashlib
import math
import random
from collections import defaultdict
from collections.abc import Callable, Hashable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Generic, TypeVar

from nightcrawler.experience.constants import (
    ALPHA_TOTAL,
    BOOTSTRAP_N,
    CLUSTER_MAX_SHARE,
    LESSON_Q,
    N_EFF_MIN_DAYS,
    OUTBOX_KEYS,
    ROUGH_RANGE_LEVEL,
    STABILITY_WEEK_SHARE,
)
from nightcrawler.learn import evidence as ev
from nightcrawler.learn.tape import tape_day

__all__ = [
    "FORWARD_SOURCES",
    "Block",
    "alpha_v",
    "check_pct",
    "utc_day",
    "iso_week",
    "operator_of",
    "hash_key",
    "row_day",
    "row_operator",
    "row_key",
    "day_blocks",
    "band",
    "e_crossed",
    "stable",
    "chance_label",
    "bar_label",
    "rough_range",
    "mean",
    "outbox_key",
    "first_per_key",
    "member_versions",
    "alpha_ledger",
    "claim_scope",
    "ebh",
    "icc",
    "n_eff",
    "independent_situations",
]

T = TypeVar("T")
B = TypeVar("B")
K = TypeVar("K", bound=Hashable)
#: Sources of forward rows (the only ones that may set a label or estimate a correlation).
FORWARD_SOURCES = ("forward", "paper")


def alpha_v(v: int) -> float:
    """The error budget of version ``v`` (1-based) of a member: ``ALPHA_TOTAL / (v (v + 1))``."""
    if v < 1:
        raise ValueError("member versions are numbered from 1")
    return ALPHA_TOTAL / (v * (v + 1))


def check_pct(alpha: float) -> str:
    """The two-sided band's coverage in words: ``"99"`` for alpha 0.01, ``"99.7"`` for 0.0033."""
    pct = 100.0 * (1.0 - alpha)
    return f"{pct:.0f}" if abs(pct - round(pct)) < 0.05 else f"{math.floor(pct * 10) / 10:.1f}"


def utc_day(ts: float) -> str:
    return tape_day(ts)


def iso_week(day: str) -> str:
    """``YYYY-Www`` of a ``YYYY-MM-DD`` day."""
    year, week, _ = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc).isocalendar()
    return f"{year}-W{week:02d}"


def operator_of(creator: str | None, symbol: str | None) -> str:
    """The creator, else the ticker family (lower-case letters and digits of the symbol), else ``"unknown"``.
    A coarse fold: the Cocoon's look-alike folding moves into ``rules/`` in phase 2."""
    if creator:
        return f"creator:{creator}"
    family = "".join(ch for ch in (symbol or "").lower() if ch.isascii() and ch.isalnum())
    return f"ticker:{family}" if family else "unknown"


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def row_day(row: Mapping[str, Any]) -> str:
    """The judged UTC day of a journal row: its ``day``, else the tape day of first_seen (else t_dec, created)."""
    day = row.get("day")
    if isinstance(day, str) and day:
        return day
    for name in ("first_seen_ts", "t_dec", "created_ts"):
        ts = row.get(name)
        if isinstance(ts, (int, float)) and math.isfinite(ts):
            return utc_day(float(ts))
    raise ValueError(f"row of {row.get('mint')} has no day")


def row_operator(row: Mapping[str, Any]) -> str:
    """A row's operator (:func:`operator_of`, carried as ``operator``); a coin is its own operator when unknown."""
    op = row.get("operator")
    return str(op) if op else f"mint:{row.get('mint')}"


def row_key(row: Mapping[str, Any]) -> str:
    """A stable identity of a journal row for hash ordering: mint, host and decision time."""
    return f"{row.get('mint')}|{row.get('host')}|{row.get('t_dec', row.get('t_in'))}"


def mean(values: Iterable[float]) -> float | None:
    items = list(values)
    return math.fsum(items) / len(items) if items else None


# --------------------------------------------------------------------------- day blocks


@dataclass(frozen=True)
class Block(Generic[T]):
    """One closed day block: its days (ascending), the units it keeps and how many the operator cap dropped."""

    days: tuple[str, ...]
    units: tuple[T, ...]
    dropped: int

    @property
    def last_day(self) -> str:
        return self.days[-1]


def _cap(units: Sequence[T], operator: Callable[[T], str], key: Callable[[T], str],
         max_share: float) -> tuple[list[T], int]:
    allowed = max(1, int(max_share * len(units) + 1e-9))
    groups: dict[str, list[int]] = defaultdict(list)
    for i, unit in enumerate(units):
        groups[operator(unit)].append(i)
    keep: set[int] = set()
    for idx in groups.values():
        keep.update(sorted(idx, key=lambda i: hash_key(key(units[i])))[:allowed])
    return [u for i, u in enumerate(units) if i in keep], len(units) - len(keep)


def day_blocks(units: Iterable[T], *, day: Callable[[T], str], operator: Callable[[T], str],
               key: Callable[[T], str], min_units: int, max_share: float = CLUSTER_MAX_SHARE) -> list[Block[T]]:
    """Closed day blocks of ``units`` (see the module docstring). Units keep their given order inside a block."""
    by_day: dict[str, list[T]] = defaultdict(list)
    for unit in units:
        by_day[day(unit)].append(unit)
    blocks: list[Block[T]] = []
    days: list[str] = []
    current: list[T] = []
    for d in sorted(by_day):
        days.append(d)
        current.extend(by_day[d])
        kept, dropped = _cap(current, operator, key, max_share)
        if len(kept) >= min_units:
            blocks.append(Block(tuple(days), tuple(kept), dropped))
            days, current = [], []
    return blocks


# --------------------------------------------------------------------------- bands and labels


def band(ys: Sequence[float], alpha: float) -> tuple[float, float]:
    """Always-valid two-sided band ``(lo, hi)`` on the mean of ``ys`` (each in [-1, 1]) at total level ``alpha``."""
    values = [ev.clip(float(y)) for y in ys]
    lo = ev.lower_bound(values, alpha / 2.0)
    hi = -ev.lower_bound([-y for y in values], alpha / 2.0)
    return lo, hi


def e_crossed(ys: Sequence[float], alpha: float, baseline: float = 0.0) -> bool:
    """Whether the e-process for H0: mean <= ``baseline`` has reached ``2 / alpha`` - a NECESSARY condition for
    ``band(ys, alpha)[0] > baseline`` (the e-value falls as the tested mean rises), and cheap to check."""
    return ev.log_e_up([ev.clip(float(y)) for y in ys], baseline) >= math.log(2.0 / alpha)


def stable(points: Sequence[tuple[str, float]], baseline: float = 0.0, *, higher_is_better: bool = True) -> bool:
    """The stability veto (G54): ``points`` are (day, value) per block in time order. The values lie on the good side
    of ``baseline`` in both halves of the record and in at least 75 % of the ISO weeks with data."""
    if len(points) < 2:
        return False
    sign = 1.0 if higher_is_better else -1.0
    half = len(points) // 2
    halves = (points[:half], points[half:])
    if any(sign * (math.fsum(v for _, v in part) / len(part) - baseline) <= 0 for part in halves):
        return False
    weeks: dict[str, list[float]] = defaultdict(list)
    for day, value in points:
        weeks[iso_week(day)].append(value)
    good = sum(sign * (math.fsum(v) / len(v) - baseline) > 0 for v in weeks.values())
    return good >= STABILITY_WEEK_SHARE * len(weeks)


def chance_label(*, measured: bool, enough: bool, lo: float | None, hi: float | None, baseline: float = 0.0,
                 stable_ok: bool) -> str:
    """§5.1 for a vs-chance card: the first label that applies."""
    if not measured:
        return "not_measured"
    if not enough or lo is None or hi is None:
        return "not_enough"
    if hi < baseline:
        return "worse"
    if lo > baseline and stable_ok:
        return "skilled"
    return "no_skill_yet"


def bar_label(*, measured: bool, enough: bool, lo: float | None, hi: float | None, bar: float,
              higher_is_better: bool = True, stable_ok: bool = True) -> str:
    """§5.1 for a vs-bar card; a bar card that is neither clearly over nor clearly under stays "Collecting"."""
    if not measured:
        return "not_measured"
    if not enough or lo is None or hi is None:
        return "not_enough"
    below = hi < bar if higher_is_better else lo > bar
    meets = lo >= bar if higher_is_better else hi <= bar
    if below:
        return "below_bar"
    if meets and stable_ok:
        return "meets_bar"
    return "not_enough"


def _quantile(sorted_values: Sequence[float], q: float) -> float:
    pos = q * (len(sorted_values) - 1)
    i = int(math.floor(pos))
    j = min(i + 1, len(sorted_values) - 1)
    return sorted_values[i] + (sorted_values[j] - sorted_values[i]) * (pos - i)


def rough_range(blocks: Sequence[B], stat: Callable[[Sequence[B]], float | None], *, seed: str,
                n: int = BOOTSTRAP_N, level: float = ROUGH_RANGE_LEVEL) -> tuple[float | None, float | None]:
    """A day-block bootstrap range of ``stat`` (resampling whole blocks; deterministic in ``seed``). Display only."""
    if not blocks:
        return None, None
    rng = random.Random(int(hash_key(seed)[:16], 16))
    values = []
    for _ in range(n):
        value = stat(rng.choices(blocks, k=len(blocks)))
        if value is not None and math.isfinite(value):
            values.append(float(value))
    if not values:
        return None, None
    values.sort()
    tail = (1.0 - level) / 2.0
    return _quantile(values, tail), _quantile(values, 1.0 - tail)


# --------------------------------------------------------------------------- outbox folds


def outbox_key(event: str, payload: Mapping[str, Any]) -> tuple[Any, ...] | None:
    """The idempotency key of an experience outbox row (None for an unknown event or a missing key field)."""
    fields = OUTBOX_KEYS.get(event)
    if fields is None or any(payload.get(f) is None for f in fields):
        return None
    return (event, *(payload[f] for f in fields))


def first_per_key(rows: Iterable[Mapping[str, Any]], events: Sequence[str] | None = None) -> list[dict[str, Any]]:
    """RECEIPTED outbox rows (``receipt_seq`` set) in receipt order, keeping the first row per idempotency key."""
    seen: set[tuple[Any, ...]] = set()
    out = []
    receipted = [r for r in rows if r.get("receipt_seq") is not None and (events is None or r.get("event") in events)]
    for row in sorted(receipted, key=lambda r: int(r["receipt_seq"])):
        payload = row.get("payload") or {}
        key = outbox_key(str(row.get("event")), payload)
        if key is None or key in seen:
            continue
        seen.add(key)
        out.append(dict(row))
    return out


def member_versions(rows: Iterable[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """``{member: [{version, hash, t0, seq}]}`` from receipted ``member_version`` rows: the v-th distinct member
    hash is version v and its ``t0`` is the receipt time."""
    out: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in first_per_key(rows, ("member_version",)):
        p = row["payload"]
        versions = out[str(p["member"])]
        versions.append({"version": len(versions) + 1, "hash": p["hash"], "t0": float(row["receipt_ts"]),
                         "seq": int(row["receipt_seq"])})
    return dict(out)


def alpha_ledger(rows: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """The α ledger per member (see the module docstring). A ``skill_claim`` counts only when it names a version
    receipted before it and asks exactly that version's α_v; its evidence starts at its own receipt (``t0``).
    Returns ``{member: {versions, spent, left, current, invalid}}``; ``current`` is the newest version."""
    versions = member_versions(rows)
    out: dict[str, dict[str, Any]] = {}
    for member, items in versions.items():
        out[member] = {"versions": [{**v, "claim": None} for v in items], "spent": 0.0, "left": ALPHA_TOTAL,
                       "current": None, "invalid": 0}
    for row in first_per_key(rows, ("skill_claim",)):
        p = row["payload"]
        entry = out.get(str(p["member"]))
        try:
            v = int(p["version"])
            alpha = float(p["alpha"])
        except (KeyError, TypeError, ValueError):
            v, alpha = 0, math.nan
        version = next((x for x in entry["versions"] if x["version"] == v), None) if entry else None
        if entry is None or version is None or version["seq"] > int(row["receipt_seq"]) \
                or not math.isclose(alpha, alpha_v(v), rel_tol=1e-9):
            if entry is not None:
                entry["invalid"] += 1
            continue
        version["claim"] = {"alpha": alpha, "metric": p.get("metric"), "seq": int(row["receipt_seq"]),
                            "t0": max(version["t0"], float(row["receipt_ts"]))}
        entry["spent"] += alpha
    for entry in out.values():
        entry["left"] = max(0.0, ALPHA_TOTAL - entry["spent"])
        entry["current"] = entry["versions"][-1] if entry["versions"] else None
    return out


def claim_scope(entry: Mapping[str, Any] | None) -> tuple[float, float] | None:
    """``(alpha, t0)`` of a member's CURRENT version claim (an :func:`alpha_ledger` entry), or None while that
    version has no receipted claim: then none of its evidence counts yet and its card stays "Collecting"."""
    current = (entry or {}).get("current")
    claim = current.get("claim") if isinstance(current, Mapping) else None
    return (float(claim["alpha"]), float(claim["t0"])) if isinstance(claim, Mapping) else None


# --------------------------------------------------------------------------- e-BH


def ebh(evalues: Mapping[K, float], q: float = LESSON_Q) -> list[K]:
    """e-BH at level ``q``: with K groups, select the k̂ largest e-values, k̂ = max{k : e_(k) >= K / (q k)}.
    Returns the selected keys, largest e-value first (ties in key order)."""
    ranked = sorted(evalues.items(), key=lambda kv: (-kv[1], str(kv[0])))
    total = len(ranked)
    k_hat = 0
    for k, (_, e) in enumerate(ranked, start=1):
        if e >= total / (q * k):
            k_hat = k
    return [key for key, _ in ranked[:k_hat]]


# --------------------------------------------------------------------------- independent situations (G53)


def icc(groups: Sequence[Sequence[float]]) -> float | None:
    """One-way ANOVA ICC(1) of values grouped by cluster, clamped to [0, 1] (None without 2 groups and spare units)."""
    groups = [list(g) for g in groups if len(g) > 0]
    k = len(groups)
    n = sum(len(g) for g in groups)
    if k < 2 or n <= k:
        return None
    grand = math.fsum(math.fsum(g) for g in groups) / n
    ssb = math.fsum(len(g) * (math.fsum(g) / len(g) - grand) ** 2 for g in groups)
    ssw = math.fsum(math.fsum((x - math.fsum(g) / len(g)) ** 2 for x in g) for g in groups)
    msb, msw = ssb / (k - 1), ssw / (n - k)
    m0 = (n - math.fsum(len(g) ** 2 for g in groups) / n) / (k - 1)
    denominator = msb + (m0 - 1.0) * msw
    if denominator <= 0:
        return 0.0
    return min(1.0, max(0.0, (msb - msw) / denominator))


def n_eff(n: float, *, m_day: float, rho_day: float, m_op: float = 1.0, rho_op: float = 0.0) -> float:
    """``n / (1 + (m_day - 1) rho_day + (m_op - 1) rho_op)``."""
    return n / (1.0 + max(0.0, m_day - 1.0) * rho_day + max(0.0, m_op - 1.0) * rho_op)


def independent_situations(rows: Iterable[Mapping[str, Any]], *, value: Callable[[Mapping[str, Any]], float],
                           day: Callable[[Mapping[str, Any]], str],
                           operator: Callable[[Mapping[str, Any]], str]) -> float | None:
    """"About N independent situations": forward rows only (history is ignored), None before 15 forward days."""
    forward = [r for r in rows if r.get("source") in FORWARD_SOURCES]
    by_day: dict[str, list[float]] = defaultdict(list)
    by_op: dict[str, list[float]] = defaultdict(list)
    for r in forward:
        x = float(value(r))
        by_day[day(r)].append(x)
        by_op[operator(r)].append(x)
    if len(by_day) < N_EFF_MIN_DAYS:
        return None
    n = len(forward)
    rho_day = icc(list(by_day.values())) or 0.0
    rho_op = icc(list(by_op.values())) or 0.0
    return n_eff(n, m_day=n / len(by_day), rho_day=rho_day, m_op=n / len(by_op), rho_op=rho_op)
