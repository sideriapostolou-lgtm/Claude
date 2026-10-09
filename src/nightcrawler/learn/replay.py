"""The shadow book: frozen variants replayed through ``backtest.Backtester`` on the tape (docs/LEARNING.md §4).

Every variant is a pure function of closed candles and its hash is receipted before the coins it is
judged on exist, so replaying it later on the sealed, hashed tape is as out-of-sample as running it
live. Rules (§4.2), applied through the backtester's optional hooks:

* observation lag: a minute is visible at ``m + 60 + L_obs`` (``L_obs`` = p75 of the engine's GT lag
  once >= 500 samples exist, :func:`estimate_l_obs`; 60 s until then);
* evaluation cadence (``decide_at``): decisions only at ``k * C + phase(mint)``, ``phase =
  int(sha256(mint)) mod C`` (``C`` = 180 s), with the newest VISIBLE candle;
* entry fill (``entry_delay_s = L_obs + L_land``): ``max(open of the candle containing the landing
  time, the close the strategy decided on)``; exits: the backtester's pessimistic intrabar rules;
* costs (``cost_fn``): :mod:`nightcrawler.costs` - pool fee tier at that market cap, constant-product
  impact from ``K_GRAD``, Ultra 10 bps, network fee, the paper broker's 100 bps haircut instead of the
  MEV buffer, all x ``cost_scale[tier]`` (>= 1); no entry when the modelled impact exceeds
  ``MAX_PRICE_IMPACT_PCT`` or the pool (both sides) is below the variant's ``min_liquidity_usd``;
* universe: SOL-quoted, not Mayhem (launch fields), then the variant's own age and market-cap
  filters and its signal (the backtester's universe check);
* graduation: no decision before the coin's ``first_seen_ts``, when the recorder first saw it in the
  GRADUATED census (it graduated at or before then). The universe is "coins that graduated", so
  buying earlier - on the bonding curve - would use the future fact that it graduates
  (research/lab: no entries before graduation).

EVIDENCE (§4.3): one observation per (variant, coin) - the net return of the FIRST $20 trade,
``x_raw = proceeds / stake - 1``, tested as ``x = clip(x_raw, -1, 1)``; ``x_stress`` charges the
trade's costs x 1.5. A coin counts only if ``coin.created_ts > variant.t0`` (forward-only; t0 = the
``register`` receipt time). A first trade still open where the tape ends is PENDING on a coin that is
still being recorded; on a closed coin (incomplete tape) it exits at ``entry x 0.5`` (x = -50 %) at its
time stop. A day is replayed only once every coin of it is closed or incomplete, and a day where fewer
than 95 % of the coins completed every fetch is excluded for every variant.

``sim_hash`` = sha256 of the bytes of ``replay.py``, ``costs.py`` and ``backtest.py``: evidence carries
it, and a change means every result is recomputed: a coin replayed again keeps only the new
simulator's outcome (no evidence row when it no longer trades), and the scoreboard scores only the
evidence of the current ``sim_hash``.
"""

from __future__ import annotations

import functools
import hashlib
import math
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from nightcrawler import backtest, costs, strategy
from nightcrawler.backtest import Backtester, CostModel
from nightcrawler.hashing import canonical_json
from nightcrawler.learn import evidence as ev
from nightcrawler.learn.gate import COMPLETENESS_MIN, COST_STRESS, PAPER_ALPHA
from nightcrawler.learn.tape import DEFAULT_L_OBS_S, TapeReader, TapeView, tape_day
from nightcrawler.learn.variants import FAMILIES, VariantSpec
from nightcrawler.models import Candle, Signal, StrategyParams

__all__ = [
    "CADENCE_S",
    "L_LAND_S",
    "STAKE_USD",
    "MISSING_DATA_RETURN",
    "COST_SCALE_VERSION",
    "LAG_MIN_SAMPLES",
    "SimConfig",
    "Outcome",
    "sim_hash",
    "estimate_l_obs",
    "phase_s",
    "decision_schedule",
    "sol_usd_asof",
    "replay_coin",
    "day_ready",
    "replay_day",
    "evidence_root",
    "update_scoreboard",
]

CADENCE_S = 180.0
L_LAND_S = 5.0
STAKE_USD = 20.0
MISSING_DATA_RETURN = -0.5
#: Version of the ``cost_scale`` table evidence was priced with (phase 2 bumps it on every ratchet).
COST_SCALE_VERSION = 1
LAG_MIN_SAMPLES = 500
_MODULE_FILES = (Path(__file__), Path(costs.__file__), Path(backtest.__file__))


@dataclass(frozen=True)
class SimConfig:
    """Simulator settings (defaults = docs/LEARNING.md §4.2). ``hooks=False`` replays with the plain
    backtester (next-open fills, its default cost model) - a reference, never evidence."""

    l_obs_s: float = DEFAULT_L_OBS_S
    cadence_s: float = CADENCE_S
    l_land_s: float = L_LAND_S
    paper_slippage_bps: float = costs.PAPER_SLIPPAGE_BPS
    max_price_impact_pct: float = 3.0
    cost_scale: Mapping[str, float] = field(default_factory=dict)
    sol_usd: float = costs.FALLBACK_SOL_USD
    stake_usd: float = STAKE_USD
    hooks: bool = True

    @classmethod
    def from_settings(cls, settings: Any, **overrides: Any) -> "SimConfig":
        """The paper haircut and the impact cap from Settings (read, never written)."""
        return cls(paper_slippage_bps=float(settings.paper_slippage_bps),
                   max_price_impact_pct=float(settings.max_price_impact_pct), **overrides)


@dataclass
class Outcome:
    """Result of one (variant, coin) replay. ``kind``: ``trade`` (evidence), ``missing`` (evidence at -50 %),
    ``none`` (no trade, final), ``pending`` (not final yet) or ``excluded`` (not eligible)."""

    kind: str
    reason: str = ""
    evidence: dict[str, Any] | None = None
    decisions: list[dict[str, Any]] = field(default_factory=list)


@functools.lru_cache(maxsize=1)
def sim_hash() -> str:
    digest = hashlib.sha256()
    for path in _MODULE_FILES:
        digest.update(path.read_bytes())
    return digest.hexdigest()


def estimate_l_obs(gt_lags: Sequence[float], default: float = DEFAULT_L_OBS_S) -> float:
    """p75 of the engine's GeckoTerminal lag samples once there are >= 500 of them, else ``default``."""
    values = sorted(float(x) for x in gt_lags if isinstance(x, (int, float)) and math.isfinite(x) and x >= 0)
    if len(values) < LAG_MIN_SAMPLES:
        return default
    return values[min(len(values) - 1, math.ceil(0.75 * len(values)) - 1)]


def phase_s(mint: str, cadence_s: float) -> int:
    """The coin's evaluation phase within the cadence (a hash of the mint)."""
    return int(hashlib.sha256(mint.encode()).hexdigest(), 16) % int(cadence_s)


def decision_schedule(mint: str, cfg: SimConfig) -> Callable[[float], float | None]:
    """``decide_at`` hook: the first scheduled evaluation while the candle that closed at ``close_ts`` is the
    newest visible one (visible from ``close_ts + L_obs`` until the next minute becomes visible)."""
    phase, cadence = phase_s(mint, cfg.cadence_s), float(int(cfg.cadence_s))

    def decide_at(close_ts: float) -> float | None:
        lo = close_ts + cfg.l_obs_s
        t = math.ceil((lo - phase) / cadence) * cadence + phase
        return t if t < lo + 60 else None

    return decide_at


def _cost_hook(cfg: SimConfig, min_liquidity_usd: float, ctx: costs.CoinCostContext, sol_usd: float,
               calls: list[tuple[str, float, float, float]]) -> Callable[[str, float, float], float]:
    def cost_fn(side: str, price: float, usd: float) -> float:
        scale = costs.cost_scale(cfg.cost_scale, price * costs.PUMP_FEE_SUPPLY)
        model = costs.replay_model(cfg.paper_slippage_bps, scale)
        fill, info = costs.side_fill(model, side, usd, price, ctx, sol_usd)
        if side == "buy" and (info["impact_pct"] > cfg.max_price_impact_pct
                              or info["liquidity_usd"] < min_liquidity_usd):
            fill = math.inf  # refused: impact cap or a pool shallower than the variant's liquidity floor
        calls.append((side, price, usd, fill))
        return fill

    return cost_fn


def _gross(calls: Sequence[tuple[str, float, float, float]]) -> float | None:
    """Return of the FIRST trade before costs, from the cost hook's calls (mid values)."""
    entry_i = next((i for i, c in enumerate(calls) if c[0] == "buy" and math.isfinite(c[3])), None)
    if entry_i is None:
        return None
    _, mid, usd, fill = calls[entry_i]
    sold = 0.0
    for side, _, value, f in calls[entry_i + 1:]:
        if side == "buy":
            if math.isfinite(f):
                break  # the second trade
            continue
        sold += value
    return sold / (usd / fill * mid) - 1.0


def sol_usd_asof(universe_rows: Iterable[Mapping[str, Any]], ts: float, default: float) -> float:
    """SOL/USD from the census rows FETCHED at or before ``ts`` (``usd_market_cap / market_cap`` of the
    newest one), else ``default``. The replay prices a coin at its creation time: leak-free."""
    best: tuple[float, float] | None = None
    for row in universe_rows:
        fetched = float(row.get("ts", math.inf))
        if fetched > ts or (best is not None and fetched <= best[0]):
            continue
        raw = row.get("raw") or {}
        try:
            value = float(raw["usd_market_cap"]) / float(raw["market_cap"])
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            continue
        if math.isfinite(value) and 1.0 < value < 10_000.0:
            best = (fetched, value)
    return default if best is None else best[1]


def replay_coin(spec: VariantSpec, view: TapeView, *, t0: float | None, closed: bool,
                cfg: SimConfig | None = None, sol_usd: float | None = None) -> Outcome:
    """Replay ``spec`` on one coin (see the module docstring). ``closed``: the recorder will add nothing more.
    ``sol_usd``: SOL/USD for the cost model (:func:`sol_usd_asof` at creation; default ``cfg.sol_usd``)."""
    cfg = cfg or SimConfig()
    created = view.created_ts
    launch = view.launch
    if t0 is None:
        return Outcome("excluded", "variant not receipted yet (no t0)")
    if created is None or launch is None:
        return Outcome("excluded", "no launch data")
    if created <= t0:
        return Outcome("excluded", "created before the variant was frozen")
    if launch.get("quote_mint") != costs.SOL_QUOTE or launch.get("mayhem"):
        return Outcome("excluded", "not SOL-quoted or Mayhem")
    if not view.complete_from_start:
        return Outcome("excluded", "early history unknown")
    candles = view.candles()
    if not candles:
        return Outcome("none" if closed else "pending", "no candles")
    params = spec.strategy_params()
    meta = {"coin": launch.get("symbol") or view.mint[:6], "mint": view.mint, "created_utc": created,
            "supply": launch.get("supply")}
    calls: list[tuple[str, float, float, float]] = []
    sizing: dict[str, Any] = {"start_usd": 5 * cfg.stake_usd, "position_pct": 0.2, "min_position_usd": cfg.stake_usd,
              "max_position_usd": cfg.stake_usd}
    signals: list[tuple[float, Signal]] = []
    family_entry = FAMILIES[spec.family].entry_fn(view.mint, created) or strategy.entry_signal

    def logged_entry(window: Sequence[Candle], snapshot: Any, p: StrategyParams, now: float) -> Signal:
        signal = family_entry(window, snapshot, p, now)
        if signal.kind == "enter":
            signals.append((now, signal))
        return signal

    if cfg.hooks:
        sol_usd = cfg.sol_usd if sol_usd is None else sol_usd
        ctx = costs.CoinCostContext()  # SOL-paired, non-Mayhem graduate: k = K_GRAD (leak-free)
        network = costs.replay_model(cfg.paper_slippage_bps).network_usd(sol_usd)
        bt = Backtester(params, CostModel(0.0, 0.0, network), **sizing,
                        cost_fn=_cost_hook(cfg, params.min_liquidity_usd, ctx, sol_usd, calls),
                        decide_at=decision_schedule(view.mint, cfg), entry_delay_s=cfg.l_obs_s + cfg.l_land_s,
                        entry_fn=logged_entry)
    else:
        bt = Backtester(params, CostModel(), **sizing, entry_fn=logged_entry)
    trades = bt.run(candles, meta, trade_from=view.first_seen_ts).trades
    filled = {id(t.signal_metrics): t.entry_ts for t in trades}
    # every ENTER signal, filled or refused at the fill (impact, liquidity): what the variant decided, when
    decisions = [{"t_dec": now, "last_ts": s.metrics.get("last_ts"), "entry_ts": filled.get(id(s.metrics)),
                  "metrics": dict(s.metrics)} for now, s in signals]
    if not trades:
        return Outcome("none" if closed else "pending", "no entry", decisions=decisions)
    first = trades[0]
    base = {"variant_hash": spec.hash, "mint": view.mint, "pricing": "replay", "entry_ts": float(first.entry_ts),
            "sim_hash": sim_hash(), "cost_scale_ver": COST_SCALE_VERSION}
    if first.exit_reason == "end_of_data":
        if not closed:
            return Outcome("pending", "first trade still open where the tape ends", decisions=decisions)
        exit_ts = float(first.entry_ts + params.max_hold_min * 60)
        row = {**base, "exit_ts": exit_ts, "x": MISSING_DATA_RETURN, "x_raw": MISSING_DATA_RETURN,
               "x_stress": MISSING_DATA_RETURN, "gross": MISSING_DATA_RETURN, "cost": 0.0}
        return Outcome("missing", "tape incomplete after entry: exits at entry x 0.5", row, decisions)
    x_raw = first.pnl_usd / first.size_usd
    gross = _gross(calls) if cfg.hooks else None
    gross = x_raw if gross is None else gross
    cost = gross - x_raw
    row = {**base, "exit_ts": float(first.exit_ts), "x": ev.clip(x_raw), "x_raw": x_raw,
           "x_stress": ev.clip(gross - COST_STRESS * cost), "gross": gross, "cost": cost}
    return Outcome("trade", first.exit_reason, row, decisions)


# --------------------------------------------------------------------------- the driver


def day_ready(store: Any, day: str) -> tuple[bool, bool, dict[str, int]]:
    """``(judged, complete, counts)``: judged once no coin of ``day`` is still open; complete when at least
    95 % of them completed every fetch (``closed``). Fixed before any result exists."""
    counts = store.day_counts(day)
    judged = counts["coins"] > 0 and counts["open"] == 0
    complete = judged and counts["closed"] >= COMPLETENESS_MIN * counts["coins"]
    return judged, complete, counts


def _previous_day(day: str) -> str:
    return tape_day(datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() - 86400)


def _spec(row: Mapping[str, Any]) -> VariantSpec:
    return VariantSpec(family=row["family"], params=dict(row["params"]), promotable=bool(row["promotable"]),
                       procedure=row.get("procedure"), name=row.get("name", ""))


def replay_day(store: Any, reader: TapeReader, day: str, now: float, cfg: SimConfig | None = None,
               should_stop: Callable[[], bool] = lambda: False) -> dict[str, int]:
    """Replay every receipted variant on every coin of a judged ``day``; one transaction per
    (variant, coin), so a killed learner resumes where it stopped. A variant finished with the day under
    this ``sim_hash`` keeps one ``replayed_days`` marker instead of a row per coin. Returns counts per outcome."""
    cfg = cfg or SimConfig()
    counts: dict[str, int] = {}
    judged, complete, _ = day_ready(store, day)
    if not judged:
        return counts
    sim = sim_hash()
    coins = reader.coins(day) if complete else {}
    census = [r for rows in coins.values() for r in rows.get("universe", ())]
    census += reader.rows(_previous_day(day), "universe") if complete else []
    sol_at_creation: dict[str, float] = {}
    for variant in store.variants():
        if variant["t0"] is None:
            continue
        spec = _spec(variant)
        if spec.hash != variant["hash"]:  # strategy.py or the family file changed: no longer this variant
            counts["stale_code"] = counts.get("stale_code", 0) + 1
            continue
        if store.day_replayed(variant["hash"], day, sim):
            continue
        done = store.replayed(variant["hash"], sim)
        finished = True
        for coin in store.coins(day=day):
            mint = coin["mint"]
            if mint in done:
                continue
            if should_stop():
                return counts
            if not complete:
                outcome = Outcome("excluded", "day below the completeness bar")
            else:
                if mint not in sol_at_creation:
                    sol_at_creation[mint] = sol_usd_asof(census, coin["created_ts"], cfg.sol_usd)
                view = TapeView(mint, as_of=now, rows=coins.get(mint, {}), l_obs=cfg.l_obs_s)
                outcome = replay_coin(spec, view, t0=variant["t0"], closed=True, cfg=cfg,
                                      sol_usd=sol_at_creation[mint])
            if outcome.kind == "pending":  # cannot happen on a judged day; never counted early
                finished = False
                continue
            with store.transaction():
                if outcome.evidence is not None:
                    store.put_evidence(outcome.evidence)
                else:  # e.g. replayed again under a new simulator: an older outcome must not linger
                    store.delete_evidence(variant["hash"], mint)
                store.mark_replayed(variant["hash"], mint, outcome.kind, sim, now)
            counts[outcome.kind] = counts.get(outcome.kind, 0) + 1
        if finished:
            store.finish_replayed_day(variant["hash"], day, sim, now)
    return counts


def evidence_root(rows: Sequence[Mapping[str, Any]]) -> str:
    """Merkle root (sha256, pairwise, last leaf promoted) over the canonical JSON of evidence rows in
    evidence order; the empty set hashes to sha256 of nothing."""
    level = [hashlib.sha256(canonical_json(dict(r)).encode("utf-8")).digest() for r in rows]
    if not level:
        return hashlib.sha256(b"").hexdigest()
    while len(level) > 1:
        level = [hashlib.sha256(level[i] + level[i + 1]).digest() if i + 1 < len(level) else level[i]
                 for i in range(0, len(level), 2)]
    return level[0].hex()


_EVIDENCE_KEYS = ("variant_hash", "mint", "pricing", "entry_ts", "exit_ts", "x", "x_raw", "x_stress", "gross",
                  "cost", "sim_hash", "cost_scale_ver")


def update_scoreboard(store: Any, now: float, cfg: SimConfig | None = None) -> dict[str, dict[str, Any]]:
    """Score every variant's replay evidence under the current ``sim_hash`` (pure :func:`evidence.score`),
    store today's scoreboard (with the trades per day of the last 7 days, for the card's ETA) and, once per
    UTC day, queue the ``scoreboard`` outbox row (evidence roots, sim_hash, cost_scale)."""
    cfg = cfg or SimConfig()
    day = tape_day(now)
    rows: dict[str, dict[str, Any]] = {}
    prev_day = store.latest_scoreboard_day()
    prev = {r["variant_hash"]: r for r in store.scoreboard(prev_day)} if prev_day else {}
    for variant in store.variants():
        evidence = [{k: e[k] for k in _EVIDENCE_KEYS} for e in store.evidence(variant["hash"], sim_hash=sim_hash())]
        stats = ev.score([e["x"] for e in evidence], threshold=variant["threshold"],
                         alpha=variant["alpha"] or PAPER_ALPHA,  # controls spend none; LB shown at the paper level
                         prev_lb=(prev.get(variant["hash"]) or {}).get("lb"))
        stats.update({"status": variant["status"], "name": variant["name"], "family": variant["family"],
                      "control": bool(FAMILIES[variant["family"]].CONTROL), "evidence_root": evidence_root(evidence),
                      "last_exit_ts": evidence[-1]["exit_ts"] if evidence else None,
                      "trades_per_day_7d": sum(e["exit_ts"] >= now - 7 * 86400 for e in evidence) / 7.0})
        store.put_scoreboard(day, variant["hash"], stats, now)
        rows[variant["hash"]] = stats
    if store.get_meta("scoreboard.receipted_day") != day:
        with store.transaction():
            store.add_outbox("scoreboard", {
                "day": day, "sim_hash": sim_hash(), "cost_scale": dict(cfg.cost_scale),
                "cost_scale_ver": COST_SCALE_VERSION,
                "variants": {h: {k: r[k] for k in ("n", "sum_x", "sum_x2", "log_e", "log_e_fut", "lb", "cusum",
                                                  "status", "evidence_root")} for h, r in rows.items()}}, now)
            store.set_meta("scoreboard.receipted_day", day)
    return rows
