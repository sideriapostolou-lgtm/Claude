"""Offline public-data research; execution-rule inference is paused.

Two streaming passes retain labels/coverage, not the large opportunity tape.
Future records cannot select a rule. The immutable test artifact is one look.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import math
import os
import statistics
import tempfile
import time
from array import array
from collections import Counter, defaultdict
from collections.abc import Iterator
from contextlib import ExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Self

DAY = 86400
FIT_HOURS, TRAIN_HOURS, TEST_HOURS = 36, 48, 72
GRACE = 30
SCHEMA = 1
MAX_WALLET_ROWS = 250_000
PROTOCOL: dict[str, Any] = {
    "name": "skipwatch-publication-association-v2", "fit_hours": FIT_HOURS,
    "train_hours": TRAIN_HOURS, "test_hours": TEST_HOURS, "reporting_grace_s": GRACE,
    "target": "block_publication_association_only", "causal_execution_inference": False,
    "edges": [0.0, 0.02, 0.04],
    "cutoffs": [30, 60], "templates": ["ask", "bid", "bid_balance", "bid_trend_depth"],
    "wallet_coverage_min": 0.90, "min_rows": {"fit": 2000, "validation": 500, "test": 500},
    "min_positive": {"fit": 50, "validation": 20, "test": 20},
    "min_windows": {"fit": 30, "validation": 20, "test": 20},
    "selection": "validation_f1_precision_fewer_predictions_stable_id",
    "sizing": "fit_positive_bin_median_buy_quantity", "returns": "unavailable",
    "sigma": "research_only_rms_at_least300_observed_adjacent_1s_returns_trailing_hour",
    "feature_coverage_min": 0.80, "depth_template": "best_bid_level_quantity",
}


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


PLAN_HASH = hashlib.sha256(_canonical(PROTOCOL)).hexdigest()


class ResearchDataError(ValueError):
    """Incomplete or contradictory evidence must not become research output."""


def candidates() -> list[dict[str, Any]]:
    return [{"id": f"{template}:{edge:.2f}:{cutoff}", "template": template,
             "edge": edge, "cutoff": cutoff}
            for template in PROTOCOL["templates"] for edge in PROTOCOL["edges"] for cutoff in PROTOCOL["cutoffs"]]


def _number(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        raise ResearchDataError("Nonfinite or nonnumeric research value")
    return float(value)


def records(directory: Path, cutoff: float, anchor: float) -> Iterator[dict[str, Any]]:
    """Read the authenticated local journal prefix, not account credentials.

    Hashes detect accidental edits/truncation; they do not certify venue truth.
    Later rows are never yielded into training analysis.
    """
    from .skipwatch import iter_records

    last_observed = -math.inf
    for row in iter_records(directory):
        if _number(row["session_started_at"]) != anchor:
            raise ResearchDataError("Prospective session origin changed")
        observed = _number(row["observed_at"])
        _number(row["at"])
        if observed < last_observed:
            raise ResearchDataError("Receipt clock moved backwards")
        last_observed = observed
        if observed >= cutoff:
            return
        if not isinstance(row["payload"], dict):
            raise ResearchDataError("Missing research payload")
        if row["kind"] in {"coverage", "wallet_fill", "opportunity", "gap", "health"}:
            yield row


@dataclass
class Label:
    quantity: float = 0.0
    fills: int = 0
    late: bool = False
    sizes: list[float] = field(default_factory=list)


class Tape:
    def __init__(self, directory: Path, anchor: float, cutoff: float) -> None:
        if not 0 < cutoff - anchor <= 73 * 3600:
            raise ResearchDataError("Research scan exceeds its fixed prospective horizon")
        self.directory, self.anchor, self.cutoff = directory, anchor, cutoff
        self.origin = math.floor(anchor)
        self.coverage = bytearray(math.ceil(cutoff) - self.origin + 2)
        self.labels: dict[tuple[str, str, int], Label] = {}
        self.label_rows: dict[str, bytes] = {}
        self.counts: Counter[str] = Counter()
        self.digest = hashlib.sha256()
        self.training_digest = hashlib.sha256()
        self._files = ExitStack()
        self.spool = self._files.enter_context(tempfile.TemporaryFile(mode="w+b"))  # noqa: SIM115 — ExitStack owns lifetime.
        wallet_gap: float | None = None
        with gzip.GzipFile(fileobj=self.spool, mode="wb", mtime=0) as output:
            for row in records(directory, cutoff, anchor):
                observed = _number(row["observed_at"])
                # A compressed journal batch may straddle the split boundary.
                # Hash actual eligible content, never its future-dependent batch hash.
                canonical = {key: row[key] for key in ("seq", "kind", "session_started_at", "at", "observed_at", "payload")}
                self.digest.update(_canonical(canonical))
                if observed < anchor + TRAIN_HOURS * 3600:
                    self.training_digest.update(_canonical(canonical))
                self.counts[str(row["kind"])] += 1
                payload = row["payload"]
                if row["kind"] == "coverage":
                    at = _number(payload.get("at", row["at"]))
                    index = math.floor(at) - self.origin
                    if 0 <= index < len(self.coverage) and at <= observed:
                        healthy = payload.get("wallet") is True
                        self.coverage[index] = (1 if healthy else 2) if self.coverage[index] != 2 else 2
                elif row["kind"] == "wallet_fill":
                    self._label(payload, observed)
                elif row["kind"] == "gap":
                    if payload.get("source") in ("wallet", "runtime", "storage", "all"):
                        start = _number(payload.get("from", row["at"]))
                        end = _number(payload.get("to") if payload.get("to") is not None else observed + 1)
                        self._mask(start, end)
                elif row["kind"] == "health":
                    if payload.get("source") == "wallet":
                        if payload.get("status") != "connected":
                            wallet_gap = observed if wallet_gap is None else wallet_gap
                        else:
                            start = payload.get("gap_from", wallet_gap)
                            if start is not None:
                                self._mask(_number(start), _number(payload.get("gap_to", observed)))
                            wallet_gap = None
                else:
                    output.write(_canonical(canonical) + b"\n")
        if wallet_gap is not None:
            self._mask(wallet_gap, cutoff)
        self.prefix = array("I", [0])
        for value in self.coverage:
            self.prefix.append(self.prefix[-1] + (value != 1))

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self._files.close()

    def _mask(self, start: float, end: float) -> None:
        low = max(0, math.floor(start) - self.origin)
        high = min(len(self.coverage), math.ceil(end) - self.origin)
        for index in range(low, high):
            self.coverage[index] = 2

    def _label(self, payload: dict[str, Any], received: float) -> None:
        identity = str(payload.get("fill_id", ""))
        if not identity:
            raise ResearchDataError("Wallet fill has no stable public-row identifier")
        comparable = {key: value for key, value in payload.items() if key != "observed_at"}
        fingerprint = hashlib.sha256(_canonical(comparable)).digest()
        if identity in self.label_rows:
            # Observation time may differ on repeated public polling, but the
            # economic row may not silently change.
            if self.label_rows[identity] != fingerprint:
                raise ResearchDataError("Repeated public fill changed")
            return
        if len(self.label_rows) >= MAX_WALLET_ROWS:
            raise ResearchDataError("Public-label memory limit reached; no subset is fitted")
        self.label_rows[identity] = fingerprint
        at = _number(payload.get("exchange_at", payload.get("at")))
        if not self.anchor <= at < self.cutoff or str(payload.get("action", "")).upper() != "BUY":
            return
        side, window = payload.get("side"), payload.get("market_id", payload.get("window"))
        if not isinstance(window, str) or not window:
            raise ResearchDataError("Unknown wallet window")
        if side not in ("up", "down"):
            # A missing public label must not become two false negatives. An
            # unrelated market has no matching opportunity and is ignored.
            for outcome in ("up", "down"):
                self.labels.setdefault((window, outcome, math.floor(at)), Label()).late = True
            return
        size, price = _number(payload["size"]), _number(payload["price"])
        if size <= 0 or not 0 <= price <= 1 or received < at:
            raise ResearchDataError("Invalid public execution")
        label = self.labels.setdefault((window, side, math.floor(at)), Label())
        label.quantity += size
        label.fills += 1
        label.sizes.append(size)
        label.late |= (at != math.floor(at) or received > math.floor(at) + 1 + GRACE)

    def covered(self, start: float, end: float) -> bool:
        low, high = math.floor(start) - self.origin, math.ceil(end) - self.origin
        return 0 <= low < high < len(self.prefix) and self.prefix[high] == self.prefix[low]

    def coverage_ratio(self, start: float, end: float) -> float:
        low = max(0, math.floor(start) - self.origin)
        high = min(len(self.coverage), math.ceil(end) - self.origin)
        return 0.0 if high <= low else 1 - (self.prefix[high] - self.prefix[low]) / (high - low)

    def opportunities(self, start: float, end: float, excluded: Counter[str]) -> Iterator[tuple[dict[str, Any], Label]]:
        seen: dict[tuple[str, str], int] = {}
        self.spool.seek(0)
        with gzip.GzipFile(fileobj=self.spool, mode="rb") as compressed, io.TextIOWrapper(compressed, encoding="utf-8") as lines:
            yield from self._opportunities(lines, start, end, excluded, seen)

    def _opportunities(self, lines: Iterator[str], start: float, end: float, excluded: Counter[str],
                       seen: dict[tuple[str, str], int]) -> Iterator[tuple[dict[str, Any], Label]]:
        for line in lines:
            row = json.loads(line)
            payload = row["payload"]
            payload.setdefault("at", row["at"])
            at = _number(payload.get("at", row["at"]))
            if not start <= at < end:
                continue
            excluded["raw"] += 1
            key = (str(payload.get("window", "")), str(payload.get("side", "")))
            second = math.floor(at)
            if key[1] not in ("up", "down") or not key[0]:
                raise ResearchDataError("Opportunity identity missing")
            if seen.get(key) == second:
                excluded["duplicate_second"] += 1
                continue
            seen[key] = second
            target = second + 1
            if target + 1 + GRACE > end:
                excluded["split_boundary"] += 1
                continue
            observed = _number(payload.get("observed_at", row["observed_at"]))
            if observed > at or _number(row["observed_at"]) > at:
                excluded["noncausal"] += 1
                continue
            flags = payload.get("coverage", {})
            if not all(flags.get(name) is True for name in ("bitcoin", "book", "wallet", "trades")):
                excluded["feature_coverage"] += 1
                continue
            if not self.covered(at, target + 1 + GRACE):
                excluded["target_coverage"] += 1
                continue
            try:
                for name in ("fair", "ask", "bid", "ask_depth", "bid_depth", "bid_top_size", "move_1s", "move_5s",
                             "move_30s", "prior_up", "prior_down", "imbalance", "window_start", "window_end"):
                    _number(payload[name])
                if not (0 <= payload["fair"] <= 1 and 0 < payload["bid"] <= payload["ask"] < 1
                        and min(payload["prior_up"], payload["prior_down"], payload["ask_depth"], payload["bid_depth"]) >= 0
                        and abs(payload["window_end"] - payload["window_start"] - 300) <= .000001
                        and payload["window_start"] <= at < payload["window_end"]):
                    raise ResearchDataError("Out-of-range feature")
            except (KeyError, ResearchDataError):
                excluded["missing_features"] += 1
                continue
            if target + 1 > payload["window_end"]:
                excluded["window_boundary"] += 1
                continue
            label = self.labels.get((key[0], key[1], target), Label())
            if label.late:
                excluded["late_or_ambiguous_label"] += 1
                continue
            yield payload, label


def predicts(rule: dict[str, Any], opportunity: dict[str, Any]) -> bool:
    remaining = opportunity["window_end"] - opportunity["at"]
    if remaining < rule["cutoff"]:
        return False
    template = rule["template"]
    quote = opportunity["ask" if template == "ask" else "bid"]
    if opportunity["fair"] - quote < rule["edge"]:
        return False
    if template == "bid_balance":
        up, down = opportunity["prior_up"], opportunity["prior_down"]
        reduces = (opportunity["side"] == "up" and up < down) or (opportunity["side"] == "down" and down < up)
        return reduces or abs(up - down) <= .25 * (up + down)
    if template == "bid_trend_depth":
        direction = 1 if opportunity["side"] == "up" else -1
        return bool(opportunity["bid_top_size"] >= 25 and direction * opportunity["move_5s"] >= 0)
    return True


def _score(counts: Counter[str]) -> dict[str, Any]:
    tp, fp, fn, tn = (counts[name] for name in ("tp", "fp", "fn", "tn"))
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "precision": tp / (tp + fp) if tp + fp else None,
            "recall": tp / (tp + fn) if tp + fn else None,
            "f1": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0.0,
            "prediction_rate": (tp + fp) / (tp + fp + fn + tn) if tp + fp + fn + tn else None}


def _update(counts: Counter[str], predicted: bool, positive: bool) -> None:
    counts[("t" if predicted == positive else "f") + ("p" if predicted else "n")] += 1


def _hash_prediction(opportunity: dict[str, Any], prevalence: float) -> bool:
    identity = f"skipwatch-v1:{opportunity['window']}:{opportunity['side']}:{math.floor(opportunity['at'])}"
    number = int.from_bytes(hashlib.sha256(identity.encode()).digest()[:8], "big") / 2**64
    return number < prevalence


class QuietRuns:
    """Consecutive eligible public seconds; missing data always breaks a run."""

    def __init__(self) -> None:
        self.active: dict[tuple[str, str], tuple[int, int]] = {}
        self.total = self.count = self.maximum = 0

    def update(self, opportunity: dict[str, Any], quiet: bool) -> None:
        key = opportunity["window"], opportunity["side"]
        second = math.floor(opportunity["at"])
        previous, run = self.active.get(key, (second - 1, 0))
        if (previous != second - 1 or not quiet) and run:
            self.total += run
            self.count += 1
            self.maximum = max(self.maximum, run)
            run = 0
        self.active[key] = second, run + 1 if quiet else 0

    def result(self) -> dict[str, Any]:
        lengths = [run for _, run in self.active.values() if run]
        count = self.count + len(lengths)
        return {"runs": count, "mean_s": (self.total + sum(lengths)) / count if count else None,
                "max_s": max(self.maximum, max(lengths, default=0)) if count else None}


def analyze(tape: Tape, name: str, start: float, end: float, rules: list[dict[str, Any]],
            *, prevalence: float = 0.0, size_estimate: float | None = None) -> dict[str, Any]:
    excluded: Counter[str] = Counter()
    scores: dict[str, Counter[str]] = {rule["id"]: Counter() for rule in rules}
    predicted_quiet = {rule["id"]: QuietRuns() for rule in rules}
    observed_quiet = QuietRuns()
    quantity_errors: dict[str, float] = defaultdict(float)
    baseline: dict[str, Counter[str]] = {key: Counter() for key in ("never", "always", "hash")}
    buckets: dict[str, Counter[str]] = defaultdict(Counter)
    sizes: list[float] = []
    fill_sizes: list[float] = []
    windows: set[str] = set()
    sides: Counter[str] = Counter()
    rows = positives = 0
    imbalance_total = absolute_error = 0.0
    for opportunity, label in tape.opportunities(start, end, excluded):
        rows += 1
        positive = label.fills > 0
        positives += positive
        windows.add(opportunity["window"])
        sides[opportunity["side"]] += 1
        imbalance_total += abs(opportunity["imbalance"])
        observed_quiet.update(opportunity, not positive)
        for rule in rules:
            guess = predicts(rule, opportunity)
            _update(scores[rule["id"]], guess, positive)
            predicted_quiet[rule["id"]].update(opportunity, not guess)
            if size_estimate is not None:
                quantity_errors[rule["id"]] += abs((size_estimate if guess else 0) - label.quantity)
        for key, guess in (("never", False), ("always", True), ("hash", _hash_prediction(opportunity, prevalence))):
            _update(baseline[key], guess, positive)
        for horizon in (1, 5, 30):
            move = opportunity[f"move_{horizon}s"]
            bucket = "negative" if move < 0 else "positive" if move > 0 else "zero"
            buckets[f"move_{horizon}s:{bucket}"].update(rows=1, buys=int(positive))
        for feature, bucket in (("depth", "below25" if opportunity["bid_top_size"] < 25 else "at_least25"),
                                ("side", opportunity["side"]),
                                ("imbalance", "above25pct" if abs(opportunity["imbalance"]) > .25 else "within25pct"),
                                ("time", "last60s" if opportunity["window_end"] - opportunity["at"] < 60 else "earlier")):
            buckets[f"{feature}:{bucket}"].update(rows=1, buys=int(positive))
        if positive:
            sizes.append(label.quantity)
            fill_sizes.extend(label.sizes)
            if size_estimate is not None:
                absolute_error += abs(label.quantity - size_estimate)
    coverage = tape.coverage_ratio(start, end)
    expected = max(0, math.floor(end) - math.floor(start) - GRACE - 1) * 2
    feature_coverage = min(1.0, rows / expected) if expected else 0.0
    reasons = []
    for failed, reason in ((coverage < PROTOCOL["wallet_coverage_min"], "wallet_coverage_below_90pct"),
                           (feature_coverage < PROTOCOL["feature_coverage_min"], "feature_coverage_below_80pct"),
                           (rows < PROTOCOL["min_rows"][name], "too_few_eligible_opportunities"),
                           (positives < PROTOCOL["min_positive"][name], "too_few_positive_bins"),
                           (len(windows) < PROTOCOL["min_windows"][name], "too_few_windows")):
        if failed:
            reasons.append(reason)
    return {"name": name, "start": start, "end": end, "rows": rows, "positive": positives,
            "negative": rows - positives, "windows": len(windows), "sides": dict(sides),
            "wallet_coverage": coverage, "exclusions": dict(excluded), "insufficient": reasons,
            "expected_side_seconds": expected, "feature_coverage": feature_coverage,
            "scores": {key: {**_score(value), "predicted_quiet_intervals": predicted_quiet[key].result(),
                              "quantity_mae_all_bins": quantity_errors[key] / rows if rows and size_estimate is not None else None}
                       for key, value in scores.items()},
            "baselines": {key: _score(value) for key, value in baseline.items()},
            "feature_buckets": {key: dict(value) for key, value in buckets.items()},
            "median_positive_bin_size": statistics.median(sizes) if sizes else None,
            "median_observed_fill_size": statistics.median(fill_sizes) if fill_sizes else None,
            "sizing_mae_positive_bins": absolute_error / positives if positives and size_estimate is not None else None,
            "observed_quiet_fraction": (rows - positives) / rows if rows else None,
            "observed_quiet_intervals": observed_quiet.result(),
            "mean_observed_abs_imbalance": imbalance_total / rows if rows else None,
            "fee_coverage": None, "net_profit_usd": None,
            "fee_reason": "Public wallet records do not establish fees, rebates or our achievable fills"}


def _atomic_new(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    value["artifact_hash"] = hashlib.sha256(_canonical(value)).hexdigest()
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                     prefix=f".{path.name}.", delete=False) as target:
        temporary = Path(target.name)
        json.dump(value, target, sort_keys=True, allow_nan=False, indent=2)
        target.write("\n")
        target.flush()
        os.fsync(target.fileno())
    try:
        os.link(temporary, path)  # immutable: another worker cannot overwrite the freeze
    finally:
        temporary.unlink(missing_ok=True)


def _load_artifact(path: Path, anchor: float) -> dict[str, Any]:
    value: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    if value.get("plan_hash") != PLAN_HASH or value.get("session_started_at") != anchor:
        raise ResearchDataError("Frozen protocol/session mismatch; no automatic re-selection")
    if value.get("artifact_hash") != hashlib.sha256(_canonical({key: item for key, item in value.items()
                                                              if key != "artifact_hash"})).hexdigest():
        raise ResearchDataError("Research artifact changed after it was frozen")
    return value


def freeze(directory: Path, now: float, anchor: float) -> dict[str, Any]:
    target = directory / "research" / "frozen.json"
    if target.exists():
        return _load_artifact(target, anchor)
    cutoff = anchor + TRAIN_HOURS * 3600
    if now < cutoff:
        raise ResearchDataError("Prospective TRAIN is not complete")
    grid = candidates()
    with Tape(directory, anchor, cutoff) as tape:
        fitted = analyze(tape, "fit", anchor, anchor + FIT_HOURS * 3600, grid)
        prevalence = fitted["positive"] / fitted["rows"] if fitted["rows"] else 0.0
        validation = analyze(tape, "validation", anchor + FIT_HOURS * 3600, cutoff, grid,
                             prevalence=prevalence, size_estimate=fitted["median_positive_bin_size"])
    ranked = sorted(grid, key=lambda rule: (-validation["scores"][rule["id"]]["f1"],
                                           -(validation["scores"][rule["id"]]["precision"] or 0),
                                           validation["scores"][rule["id"]]["tp"] + validation["scores"][rule["id"]]["fp"], rule["id"]))
    selected = ranked[0]
    selected_score = validation["scores"][selected["id"]]
    beats = all(selected_score["f1"] > validation["baselines"][key]["f1"]
                and (selected_score["precision"] or 0) > (validation["baselines"][key]["precision"] or 0)
                for key in ("always", "hash"))
    enough = not fitted["insufficient"] and not validation["insufficient"]
    result = {"version": SCHEMA, "plan_hash": PLAN_HASH, "protocol": PROTOCOL, "session_started_at": anchor,
              "frozen_at": now, "training_cutoff": cutoff, "freeze_late_seconds": max(0, now - cutoff),
              "input_digest": tape.digest.hexdigest(), "source_counts": dict(tape.counts),
              "stages_read": ["fit", "validation"], "status": "frozen" if enough and beats else
              "insufficient_training" if not enough else "no_block_publication_association",
              "candidate": selected, "prevalence": prevalence, "size_estimate": fitted["median_positive_bin_size"],
              "fit": fitted, "validation": validation, "live_promotion": False,
              "causal_execution_inference": False,
              "interpretation": "Block-publication association only; features may be AFTER actual execution"}
    _atomic_new(target, result)
    return result


def evaluate(directory: Path, now: float, anchor: float) -> dict[str, Any]:
    target = directory / "research" / "test.json"
    if target.exists():
        return _load_artifact(target, anchor)
    frozen_path = directory / "research" / "frozen.json"
    if not frozen_path.exists():
        raise ResearchDataError("Training artifact must be frozen before TEST is read")
    frozen = _load_artifact(frozen_path, anchor)
    if frozen["status"] != "frozen":
        raise ResearchDataError("Training did not qualify; TEST must remain unread")
    cutoff = anchor + TEST_HOURS * 3600
    if now < cutoff:
        raise ResearchDataError("Prospective TEST is not complete")
    with Tape(directory, anchor, cutoff) as tape:
        if tape.training_digest.hexdigest() != frozen["input_digest"]:
            raise ResearchDataError("Training source changed after freeze")
        tested = analyze(tape, "test", anchor + TRAIN_HOURS * 3600, cutoff, [frozen["candidate"]],
                         prevalence=frozen["prevalence"], size_estimate=frozen["size_estimate"])
    score = tested["scores"][frozen["candidate"]["id"]]
    beats = all(score["f1"] > tested["baselines"][key]["f1"]
                and (score["precision"] or 0) > (tested["baselines"][key]["precision"] or 0)
                for key in ("always", "hash"))
    result = {"version": SCHEMA, "plan_hash": PLAN_HASH, "session_started_at": anchor, "evaluated_at": now,
              "candidate": frozen["candidate"], "frozen_artifact_hash": hashlib.sha256(_canonical(frozen)).hexdigest(),
              "input_digest": tape.digest.hexdigest(), "test": tested, "live_promotion": False,
              "status": "insufficient_evidence" if frozen["status"] != "frozen" or tested["insufficient"] else
              "block_publication_association_only" if beats else "no_block_publication_association",
              "net_profit_usd": None, "transfer_to_kalshi": "untested_5m_to_15m_hypothesis"}
    result["causal_execution_inference"] = False
    result["interpretation"] = "Block-publication association only; not execution triggers or trading rules"
    _atomic_new(target, result)
    return result


def _rulebook(directory: Path, status: dict[str, Any]) -> None:
    path = directory / "research" / "RULES.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    stage = status["status"]
    candidate = status.get("candidate")
    text = ("# Block-publication association research\n\n"
            f"Status: **{stage}**. No real-money rule has been activated.\n\n"
            "The preregistered clock uses 36 hours fitting, 12 hours validation, then one separate 24-hour test. "
            "The target is the wallet row's BLOCK timestamp, not its execution time. Features may follow the actual trade. "
            "These associations cannot identify execution triggers or justify trading rules.\n\n")
    if candidate:
        text += f"Frozen association candidate: `{candidate['id']}`. This is not an execution rule and not the wallet's exact private algorithm.\n\n"
    detail = status.get("test", status.get("validation"))
    if detail:
        text += (f"Eligible opportunities: {detail['rows']}; positive seconds: {detail['positive']}; "
                 f"wallet coverage: {detail['wallet_coverage']:.1%}. "
                 f"Missing-evidence reasons: {', '.join(detail['insufficient']) or 'none at the preregistered minimums'}.\n\n")
        if candidate:
            score = detail["scores"][candidate["id"]]
            text += f"Precision: {score['precision']}; recall: {score['recall']}; F1: {score['f1']}. See JSON for all baselines and exclusions.\n\n"
    text += ("Fees, rebates, private orders, cancellations, queue position and achievable net returns are unknown. "
             "Coinbase fair value is a proxy; the five-minute venue settles on Chainlink's specified TWAP. "
             "A five-to-fifteen-minute Kalshi transfer remains untested, with different fees, liquidity and settlement. "
             "Evidence here cannot enable trading or change the owner's caps.\n")
    if stage == "awaiting_verified_execution_time":
        text = ("# Pending: execution timing is unresolved\n\n"
                "Strategy fitting is paused. The public wallet timestamp is block inclusion time, "
                "not execution time. Prices immediately before that block timestamp can follow the trade. "
                "No causal rule, strategy score or trading verdict is available.\n\n"
                "Observation continues with the original start time and raw tape preserved. "
                "The original 48/72-hour split boundaries are not scheduled automatic verdicts. "
                "A separate preregistered execution-timing protocol is required before fitting can resume. "
                "Existing frozen/test artifacts are preserved without reading or reusing their metrics. "
                "Nothing here activates real money.\n")
    temporary = path.with_suffix(".tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def run_due(directory: Path, now: float, session_started_at: float, *,
            block_publication_research: bool = False) -> dict[str, Any]:
    """Production only reports the timing pause and never scans/fits the tape.

    An explicit Python research call may inspect noncausal block-publication
    associations. The production CLI deliberately provides no bypass switch.
    """
    blocked_path = directory / "research" / "blocked.json"
    phase = "train_freeze"
    try:
        _number(now)
        _number(session_started_at)
        if not block_publication_research:
            paused = {"status": "awaiting_verified_execution_time", "session_started_at": session_started_at,
                    "freeze_due_at": session_started_at + TRAIN_HOURS * 3600,
                    "test_due_at": session_started_at + TEST_HOURS * 3600,
                    "automatic_verdict_scheduled": False, "live_promotion": False,
                    "causal_execution_inference": False,
                    "reason": "Wallet timestamps identify block inclusion, not execution time; strategy fitting is paused",
                    "summary": {"stage": "timing_unverified", "precision": None, "recall": None, "f1": None,
                                "coverage": None, "feature_coverage": None, "rows": None,
                                "reasons": ["Keep collecting; a new preregistered execution-timing protocol is required"]}}
            _rulebook(directory, paused)
            return paused
        if blocked_path.exists():
            return _load_artifact(blocked_path, session_started_at)
        if now < session_started_at + TRAIN_HOURS * 3600:
            status: dict[str, Any] = {"status": "collecting_train", "session_started_at": session_started_at,
                                      "freeze_due_at": session_started_at + TRAIN_HOURS * 3600,
                                      "test_due_at": session_started_at + TEST_HOURS * 3600, "live_promotion": False}
        else:
            status = freeze(directory, now, session_started_at)
            if now >= session_started_at + TEST_HOURS * 3600 and status["status"] == "frozen":
                phase = "held_out"
                status = evaluate(directory, now, session_started_at)
            elif status["status"] != "frozen":
                status = {**status, "holdout_status": "unread"}
        detail = status.get("test", status.get("validation"))
        chosen = status.get("candidate")
        score = detail["scores"][chosen["id"]] if detail and chosen else {}
        status = {**status, "causal_execution_inference": False,
                  "interpretation": "Noncausal block-publication association only; not execution triggers or trading rules",
                  "freeze_due_at": session_started_at + TRAIN_HOURS * 3600,
                  "test_due_at": session_started_at + TEST_HOURS * 3600, "summary": {
            "stage": "held_out" if "test" in status else "validation" if detail else "collecting",
            "precision": score.get("precision"), "recall": score.get("recall"), "f1": score.get("f1"),
            "coverage": detail["wallet_coverage"] if detail else None,
            "feature_coverage": detail["feature_coverage"] if detail else None,
            "rows": detail["rows"] if detail else None,
            "reasons": detail["insufficient"] if detail else ["Future prospective observations required"]}}
        _rulebook(directory, status)
        return status
    except (OSError, EOFError, ValueError, KeyError, TypeError) as exc:
        # Fixed reason only: never serialize arbitrary file/request contents.
        failure = {"status": "research_blocked", "reason": type(exc).__name__, "live_promotion": False,
                   "causal_execution_inference": False,
                   "plan_hash": PLAN_HASH, "session_started_at": session_started_at, "phase": phase,
                   "summary": {"stage": "blocked", "precision": None, "recall": None, "f1": None,
                               "coverage": None, "feature_coverage": None, "rows": None,
                               "reasons": ["Source integrity or incomplete evidence needs review"]}}
        if isinstance(exc, OSError):
            # A transient disk problem may recover. The scheduler uses this
            # explicit delay instead of rescanning gigabytes every minute.
            failure["retry_after_s"] = 3600
        elif not blocked_path.exists():
            try:
                _atomic_new(blocked_path, failure)
                _rulebook(directory, failure)
            except OSError:
                failure["retry_after_s"] = 3600
        return failure


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, nargs="?", help="Watcher journal directory")
    parser.add_argument("--data-dir", type=Path, help="Watcher journal directory")
    parser.add_argument("--session-start", "--session-started-at", dest="session_start", type=float,
                        required=True, help="Original persisted prospective start, epoch seconds")
    parser.add_argument("--now", type=float, default=None, help="Evidence clock, epoch seconds (default current time)")
    arguments = parser.parse_args()
    directory = arguments.data_dir or arguments.directory
    if directory is None:
        parser.error("A watcher data directory is required")
    if hasattr(os, "nice"):
        os.nice(10)  # CPU-heavy prospective research yields priority to the financial process.
    status = run_due(directory, arguments.now if arguments.now is not None else time.time(), arguments.session_start)
    keys = ("status", "reason", "summary", "candidate", "session_started_at", "frozen_at", "evaluated_at",
            "freeze_due_at", "test_due_at", "holdout_status", "live_promotion", "retry_after_s",
            "automatic_verdict_scheduled", "causal_execution_inference")
    print(json.dumps({key: status[key] for key in keys if key in status}, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
