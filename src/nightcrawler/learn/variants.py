"""Frozen strategy variants: spec schema, hard bounds, Settings anchors, identity, seeds and registration
(docs/LEARNING.md §5.2, §7, §8).

* A spec holds STRATEGY parameters only (the fields of :class:`~nightcrawler.models.StrategyParams`),
  resolved in full against the Settings strategy (the ANCHOR) at registration, so a variant never
  changes when Settings do. Any other key - a risk setting, a made-up name - is refused, and so is
  a tunable outside its hard range (:data:`BOUNDS`). A stop and a time stop are always present.
* Safety filters are anchored to Settings and may only TIGHTEN (:data:`ANCHORS`). A spec that
  loosens one may still run in the shadow (it measures what the filter is worth) but is
  ``promotable = False``: it can never become champion.
* ``variant_hash = sha256(canonical_json({schema, family, family_code_sha256, params, procedure}))``
  where ``family_code_sha256`` hashes the bytes of ``strategy.py`` plus the family file
  (``procedure`` is None in v1).
* Registration (:func:`register`) caches the variant in learn.db and queues its ``register``
  receipt; ``t0`` is the receipt's time. A seed is checked on its own: one the Settings anchor puts
  outside a hard range (a valid MAX_HOLD_MIN=480, say) is skipped with its reason
  (:func:`rejected_seeds`) and the others still register - it never stops the learner. At most
  :data:`~nightcrawler.learn.gate.REG_PER_ISO_WEEK` non-control registrations per ISO week (seeds,
  search and proposals combined; unused allowance does not roll over); controls (the placebo) are
  exempt and spend no alpha.
"""

from __future__ import annotations

import dataclasses
import functools
import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any, Mapping

from nightcrawler import strategy
from nightcrawler.hashing import canonical_json
from nightcrawler.learn.families import dip_rebound, placebo
from nightcrawler.learn.gate import PAPER_ALPHA, PAPER_THRESHOLD, REG_PER_ISO_WEEK
from nightcrawler.models import StrategyParams

__all__ = [
    "SPEC_SCHEMA",
    "FAMILIES",
    "BOUNDS",
    "ANCHORS",
    "SEEDS_PATH",
    "SpecRejected",
    "VariantSpec",
    "make_spec",
    "family_code_sha256",
    "variant_hash",
    "describe",
    "load_seeds",
    "seed_specs",
    "rejected_seeds",
    "iso_week",
    "registrations_this_week",
    "register",
    "register_seeds",
]

SPEC_SCHEMA = 1
FAMILIES: dict[str, ModuleType] = {"dip_rebound": dip_rebound, "placebo": placebo}
SEEDS_PATH = Path(__file__).with_name("seeds.json")
_FAMILY_DIR = Path(__file__).parent / "families"

#: Hard ranges of the tunable strategy parameters (docs/LEARNING.md §7; inclusive).
BOUNDS: dict[str, tuple[float, float]] = {
    "stop_loss_pct": (0.05, 0.35),
    "max_hold_min": (5, 360),
    "take_profit_pct": (0.05, 3.0),
    "trail_pct": (0.05, 0.5),
    "dip_pct": (0.2, 0.9),
    "confirm_green": (1, 4),
    "min_buy_sell_ratio": (0.5, 3.0),
    "dip_lookback_h": (0.5, 12.0),
    "partial_tp_fraction": (0.1, 1.0),
}
#: Safety filters anchored to Settings: "floor" may only rise, "ceiling" may only fall.
ANCHORS: dict[str, str] = {
    "min_age_min": "floor",
    "max_age_h": "ceiling",
    "min_mcap_usd": "floor",
    "max_mcap_usd": "ceiling",
    "min_liquidity_usd": "floor",
    "cooldown_min": "floor",
}
_TYPES = {f.name: (int if f.type in ("int", int) else float) for f in dataclasses.fields(StrategyParams)}


class SpecRejected(ValueError):
    """A spec that may not be registered (unknown/risk key, out of bounds, unknown family)."""


@dataclass(frozen=True)
class VariantSpec:
    """A frozen variant: family + the FULL strategy parameter set (+ procedure, None in v1)."""

    family: str
    params: dict[str, Any]
    promotable: bool
    procedure: dict[str, Any] | None = None
    name: str = field(default="", compare=False)

    @property
    def hash(self) -> str:
        return variant_hash(self.family, self.params, self.procedure)

    @property
    def control(self) -> bool:
        return bool(FAMILIES[self.family].CONTROL)

    def strategy_params(self) -> StrategyParams:
        return StrategyParams(**self.params)


def make_spec(family: str, overrides: Mapping[str, Any], anchor: StrategyParams, *,
              procedure: Mapping[str, Any] | None = None) -> VariantSpec:
    """The anchor's parameters with ``overrides`` applied, validated (see the module docstring)."""
    module = FAMILIES.get(family)
    if module is None:
        raise SpecRejected(f"unknown family {family!r}")
    for key in overrides:
        if key not in _TYPES:
            raise SpecRejected(f"{key!r} is not a strategy parameter (risk and control settings are out of reach)")
    params: dict[str, Any] = {}
    for key, value in {**anchor.to_dict(), **dict(overrides)}.items():
        try:
            params[key] = _TYPES[key](value)
        except (TypeError, ValueError):
            raise SpecRejected(f"{key}={value!r} is not a number") from None
        if not math.isfinite(params[key]):
            raise SpecRejected(f"{key} must be finite")
    for key, (lo, hi) in BOUNDS.items():
        if not lo <= params[key] <= hi:
            raise SpecRejected(f"{key}={params[key]} outside its hard range [{lo}, {hi}]")
    if params["min_mcap_usd"] >= params["max_mcap_usd"]:
        raise SpecRejected("min_mcap_usd must be below max_mcap_usd")
    base = anchor.to_dict()
    loosened = [key for key, kind in ANCHORS.items()
                if (params[key] < base[key] if kind == "floor" else params[key] > base[key])]
    spec = VariantSpec(family=family, params=params, promotable=bool(module.PROMOTABLE) and not loosened,
                       procedure=dict(procedure) if procedure is not None else None)
    return dataclasses.replace(spec, name=describe(spec))


@functools.lru_cache(maxsize=None)
def family_code_sha256(family: str) -> str:
    """sha256 of the bytes of ``strategy.py`` followed by ``learn/families/<family>.py`` (read once per process)."""
    digest = hashlib.sha256(Path(strategy.__file__).read_bytes())
    digest.update((_FAMILY_DIR / f"{family}.py").read_bytes())
    return digest.hexdigest()


def variant_hash(family: str, params: Mapping[str, Any], procedure: Mapping[str, Any] | None) -> str:
    body = {"schema": SPEC_SCHEMA, "family": family, "family_code_sha256": family_code_sha256(family),
            "params": dict(params), "procedure": procedure}
    return hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()


def describe(spec: VariantSpec) -> str:
    """Plain-words name for the dashboard, e.g. ``"dip 45%, stop 20%, tp 40% (half), 120 min"``."""
    if spec.control:
        return "random entry (control)"
    p = spec.params
    half = " (half)" if p["partial_tp_fraction"] < 1.0 else ""
    return (f"dip {p['dip_pct']:.0%}, stop {p['stop_loss_pct']:.0%}, tp {p['take_profit_pct']:.0%}{half}, "
            f"{p['max_hold_min']:.0f} min")


def load_seeds(path: str | Path = SEEDS_PATH) -> list[dict[str, Any]]:
    return list(json.loads(Path(path).read_text(encoding="utf-8"))["seeds"])


def _checked_seeds(anchor: StrategyParams, path: str | Path) -> list[tuple[dict[str, Any], VariantSpec | str]]:
    """Each seed with its spec, or with why it is refused under this anchor."""
    out: list[tuple[dict[str, Any], VariantSpec | str]] = []
    for seed in load_seeds(path):
        try:
            out.append((seed, make_spec(seed["family"], seed.get("params") or {}, anchor)))
        except SpecRejected as exc:
            out.append((seed, str(exc)))
    return out


def seed_specs(anchor: StrategyParams, path: str | Path = SEEDS_PATH) -> list[VariantSpec]:
    """The seeds this anchor allows (a seed it puts out of bounds is left out: :func:`rejected_seeds`)."""
    return [spec for _, spec in _checked_seeds(anchor, path) if isinstance(spec, VariantSpec)]


def rejected_seeds(anchor: StrategyParams, path: str | Path = SEEDS_PATH) -> list[str]:
    """``"<seed note>: <reason>"`` for every seed this anchor puts outside a hard range."""
    return [f"{seed.get('note') or seed['family']}: {why}" for seed, why in _checked_seeds(anchor, path)
            if isinstance(why, str)]


def iso_week(ts: float) -> tuple[int, int]:
    year, week, _ = datetime.fromtimestamp(float(ts), tz=timezone.utc).isocalendar()
    return year, week


def registrations_this_week(store: Any, now: float) -> int:
    """Non-control registrations created in ``now``'s ISO week."""
    week = iso_week(now)
    return sum(1 for row in store.variants()
               if not FAMILIES[row["family"]].CONTROL and iso_week(row["created_ts"]) == week)


def register(store: Any, spec: VariantSpec, *, source: str, now: float) -> bool:
    """Register ``spec`` (see the module docstring). False when already registered or when this ISO
    week's allowance is spent (the caller retries next week)."""
    if store.variant(spec.hash) is not None:
        return False
    if not spec.control and registrations_this_week(store, now) >= REG_PER_ISO_WEEK:
        return False
    return store.add_variant(spec.hash, family=spec.family, params=spec.params, source=source,
                             alpha=0.0 if spec.control else PAPER_ALPHA, threshold=PAPER_THRESHOLD,
                             promotable=spec.promotable, name=spec.name, now=now, procedure=spec.procedure)


def register_seeds(store: Any, anchor: StrategyParams, now: float) -> list[str]:
    """Register the seeds not registered yet (first boot: 4 within the week-1 allowance + the placebo); a seed
    the anchor puts out of bounds is skipped (:func:`rejected_seeds`)."""
    return [spec.hash for spec in seed_specs(anchor) if register(store, spec, source="seed", now=now)]
