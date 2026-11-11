"""Prospective public-event predictions and strict, one-to-one research scoring.

No public timestamp is currently approved as an execution-clock bound. Proxy
scores never satisfy the execution target or enable trading.
"""

from __future__ import annotations

import hashlib
import math
from collections import Counter, deque
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .skipwatch_fit import ResearchDataError, _canonical, _number, candidates, predicts

PROTOCOL: dict[str, Any] = {
    "id": "skipwatch-execution-v3", "version": 1, "recall_target": .70, "precision_reporting_required": True,
    "time_tolerance_s": 5.0, "price_tolerance_usd": .02, "causal_before_event": True,
    "one_to_one": True, "all_source_fills_denominator": True,
    "target_actions": ["buy", "sell", "unknown"], "prediction_action": "buy",
    "grid": candidates(), "decision_interval_s": 1, "max_predictions_per_candidate_bin": 1,
    "feature_source": "Coinbase proxy; other BTC feeds are diagnostics only",
    "selection": "validation_f1_precision_fewer_predictions_stable_id",
    "assignment": "maximum_cardinality_deterministic_sorted_augmenting_paths",
    "study_status": "unqualified_public_event_shadow", "automatic_promotion": False,
}
PROTOCOL_HASH = hashlib.sha256(_canonical(PROTOCOL)).hexdigest()
# A caller-controlled JSON boolean cannot qualify an execution timestamp.
# A later reviewed protocol must add documented, versioned evidence here.
QUALIFIED_EXECUTION_TIMING: frozenset[str] = frozenset()
BASELINES = ("baseline:never", "baseline:dense_both_sides", "baseline:single_edge")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _valid_feature(payload: dict[str, Any], issued_at: float) -> bool:
    try:
        at = _number(payload["at"])
        if not 0 <= issued_at - at <= 1 or _number(payload["observed_at"]) > issued_at:
            return False
        start, end = _number(payload["window_start"]), _number(payload["window_end"])
        if end - start != 300 or not start <= at < end or payload["side"] not in {"up", "down"}:
            return False
        for key in ("bitcoin", "book", "wallet", "trades"):
            if payload["coverage"].get(key) is not True:
                return False
        fair, bid, ask = (_number(payload[key]) for key in ("fair", "bid", "ask"))
        if not 0 <= fair <= 1 or not 0 < bid < ask < 1:
            return False
        for key in ("prior_up", "prior_down", "bid_top_size"):
            if _number(payload[key]) < 0:
                return False
        _number(payload["move_5s"])
        for venue in payload.get("bitcoin_venues", {}).values():
            if (isinstance(venue, dict) and venue.get("received_at") is not None
                    and _number(venue["received_at"]) > issued_at):
                return False
        return True
    except (ValueError, KeyError, TypeError, AttributeError):
        return False


class PredictionRecorder:
    """Emit fixed-grid shadow predictions only after both features were recorded.

    The runtime journals returned batches; replay calls restore, never observe.
    No fitted rule, qualified epoch or holdout clock is created by this recorder.
    """

    def __init__(self, original_session_started_at: float) -> None:
        self.origin = _number(original_session_started_at)
        self.started_at: float | None = None
        self.pending: dict[tuple[str, int], dict[str, tuple[dict[str, Any], int]]] = {}
        self.last_bins: dict[str, int] = {}

    def restore(self, kind: str, payload: dict[str, Any]) -> None:
        if kind != "execution_prediction_batch":
            return
        if payload.get("protocol_hash") != PROTOCOL_HASH:
            return  # A changed protocol begins a separately identified shadow epoch.
        if _number(payload["original_session_started_at"]) != self.origin:
            raise ResearchDataError("Prediction journal origin mismatch")
        started = _number(payload["shadow_started_at"])
        if self.started_at is not None and started != self.started_at:
            raise ResearchDataError("Prediction shadow epoch changed")
        self.started_at = started
        window = str(payload["window"])
        self.last_bins[window] = max(self.last_bins.get(window, -1), int(payload["decision_bin"]))

    def observe(self, payload: dict[str, Any], *, seq: int, issued_at: float,
                monotonic_ns: int, clock_id: str) -> list[dict[str, Any]]:
        now = _number(issued_at)
        if seq <= 0 or monotonic_ns < 0 or not clock_id or not _valid_feature(payload, now):
            return []
        window, side = str(payload["window"]), str(payload["side"])
        second = math.floor(_number(payload["at"]))
        if second <= self.last_bins.get(window, -1):
            return []
        self.pending = {key: value for key, value in self.pending.items() if key[1] >= second - 1}
        self.last_bins = {key: value for key, value in self.last_bins.items() if value >= second - 7200}
        pair = self.pending.setdefault((window, second), {})
        pair.setdefault(side, (dict(payload), seq))  # earliest same-second features, never a better later quote
        if set(pair) != {"up", "down"}:
            return []
        del self.pending[(window, second)]
        self.last_bins[window] = second
        up, down = pair["up"][0], pair["down"][0]
        if up["at"] != down["at"] or any(not _valid_feature(row, now) for row in (up, down)):
            return []
        if self.started_at is None:
            self.started_at = now
        predictions = []
        for rule in PROTOCOL["grid"]:
            quote = "ask" if rule["template"] == "ask" else "bid"
            eligible = [row for row in (up, down) if predicts(rule, row)]
            if eligible:
                row = min(eligible, key=lambda item: (-(item["fair"] - item[quote]), item["side"] != "up"))
                predictions.append(self._prediction(rule["id"], row, quote, second))
        for row in (up, down):
            predictions.append(self._prediction("baseline:dense_both_sides", row, "ask", second))
        single = min((up, down), key=lambda row: (-(row["fair"] - row["ask"]), row["side"] != "up"))
        predictions.append(self._prediction("baseline:single_edge", single, "ask", second))
        return [{"schema": 1, "protocol_id": PROTOCOL["id"], "protocol_hash": PROTOCOL_HASH,
                 "original_session_started_at": self.origin, "shadow_started_at": self.started_at,
                 "qualified_epoch_started_at": None, "scope": "unqualified_public_event_shadow",
                 "causal_execution_timing_verified": False, "at": now, "observed_at": now,
                 "issued_monotonic_ns": monotonic_ns, "receipt_clock_id": clock_id,
                 "window": window, "window_start": up["window_start"], "window_end": up["window_end"],
                 "decision_bin": second, "feature_prefix_seq": max(value[1] for value in pair.values()),
                 "feature_evidence": [{"side": side, "seq": pair[side][1], "at": pair[side][0]["at"],
                                        "hash": _digest(pair[side][0])} for side in ("up", "down")],
                 "predictions": predictions, "live_promotion": False}]

    @staticmethod
    def _prediction(candidate: str, row: dict[str, Any], quote: str, second: int) -> dict[str, Any]:
        identity = _digest([PROTOCOL_HASH, candidate, row["window"], second, row["side"]])
        return {"prediction_id": identity, "candidate_id": candidate, "side": row["side"],
                "action": "buy", "price": row[quote], "quantity": None, "price_source": quote}


@dataclass(frozen=True, slots=True)
class Prediction:
    identity: str
    window: str
    side: str
    price: float
    at: float


@dataclass(frozen=True, slots=True)
class FillLabel:
    identity: str
    window: str
    side: str
    price: float
    # Public-event associations are NOT engine execution-clock evidence.
    proxy_at: float | None = None
    print_id: str | None = None
    execution_low: float | None = None
    execution_high: float | None = None
    timing_evidence_hash: str | None = None
    settled_identity_verified: bool = False
    action: str = "buy"


def _matching(predictions: list[Prediction], labels: list[FillLabel], mode: str) -> list[tuple[str, str]]:
    """Maximum-cardinality deterministic matching, independently per window."""
    print_counts = Counter(row.print_id for row in labels if row.print_id)
    result: list[tuple[str, str]] = []
    for window in sorted({row.window for row in predictions}):
        ps = sorted((row for row in predictions if row.window == window), key=lambda row: (row.at, row.identity))
        fs = sorted((row for row in labels if row.window == window), key=lambda row: row.identity)
        if len(ps) > 2000 or len(fs) > 20000:
            raise ResearchDataError("Research window exceeds bounded matching capacity")
        edges: dict[int, list[int]] = {}
        for i, prediction in enumerate(ps):
            possible = []
            for j, fill in enumerate(fs):
                if fill.action == "sell" or (mode != "possible" and fill.action != "buy"):
                    continue
                if fill.side not in {prediction.side, "unknown"} or abs(prediction.price - fill.price) > .02 + 1e-12:
                    continue
                if mode != "possible" and fill.side == "unknown":
                    continue
                if mode == "possible":
                    eligible, distance = True, 0.0
                elif mode == "proxy":
                    eligible = (fill.proxy_at is not None and fill.print_id is not None
                                and print_counts[fill.print_id] == 1 and 0 < fill.proxy_at - prediction.at <= 5)
                    distance = abs((fill.proxy_at or 0) - prediction.at)
                else:
                    eligible = (fill.settled_identity_verified and fill.timing_evidence_hash in QUALIFIED_EXECUTION_TIMING
                                and fill.execution_low is not None and fill.execution_high is not None
                                and prediction.at < fill.execution_low <= fill.execution_high <= prediction.at + 5)
                    distance = abs((fill.execution_low or 0) - prediction.at)
                if eligible:
                    possible.append((distance, abs(prediction.price - fill.price), fill.identity, j))
            edges[i] = [item[3] for item in sorted(possible)]
        # An augmenting path can reassign an earlier prediction. Nearest-neighbor
        # greedy alone can undercount or reuse fills when tolerance windows overlap.
        owner: dict[int, int] = {}
        assigned: dict[int, int] = {}
        for start in range(len(ps)):
            queue = deque([start])
            previous: dict[int, tuple[int, int] | None] = {start: None}
            end: tuple[int, int] | None = None
            while queue and end is None:
                current = queue.popleft()
                for fill_index in edges[current]:
                    if fill_index not in owner:
                        end = current, fill_index
                        break
                    other = owner[fill_index]
                    if other not in previous:
                        previous[other] = current, fill_index
                        queue.append(other)
            if end is not None:
                current, fill_index = end
                while True:
                    owner[fill_index] = current
                    assigned[current] = fill_index
                    step = previous[current]
                    if step is None:
                        break
                    current, fill_index = step
        result.extend((ps[i].identity, fs[j].identity) for i, j in sorted(assigned.items()))
    return result


def score(predictions: Iterable[Prediction], labels: Iterable[FillLabel]) -> dict[str, Any]:
    ps, fs = list(predictions), list(labels)
    if len({row.identity for row in ps}) != len(ps) or len({row.identity for row in fs}) != len(fs):
        raise ResearchDataError("Scoring identities are not unique")
    rows: list[Prediction | FillLabel] = [*ps, *fs]
    for row in rows:
        if row.side not in {"up", "down", "unknown"} or not 0 < _number(row.price) < 1:
            raise ResearchDataError("Invalid scoring side or price")
    for prediction in ps:
        _number(prediction.at)
        if prediction.side == "unknown":
            raise ResearchDataError("Predictions require one explicit side")
    for fill in fs:
        if fill.action not in {"buy", "sell", "unknown"}:
            raise ResearchDataError("Unknown action must be explicitly labeled")
        for stamp in (fill.proxy_at, fill.execution_low, fill.execution_high):
            if stamp is not None:
                _number(stamp)
    strict, proxy, possible = (_matching(ps, fs, mode) for mode in ("strict", "proxy", "possible"))
    n, p = len(fs), len(ps)
    strict_hits, proxy_hits, upper_hits = len(strict), len(proxy), len(possible)
    eligible_prints = Counter(row.print_id for row in fs if row.print_id)
    proxy_identified = sum(row.proxy_at is not None and row.print_id is not None
                           and eligible_prints[row.print_id] == 1 for row in fs)
    return {"protocol_id": PROTOCOL["id"], "protocol_hash": PROTOCOL_HASH,
            "status": "awaiting_verified_execution_time", "held_out": False,
            "target_scope": "all observed BTC five-minute fill actions; predictions are BUY only",
            "time_tolerance_s": 5, "price_tolerance_usd": .02, "causal_before_event": True,
            "one_to_one": True, "all_source_fills_denominator": True,
            "source_fill_rows": n, "predictions": p, "timing_validated": False,
            "source_actions": dict(Counter(row.action for row in fs)),
            "identity_validated": False, "coverage_validated": False, "anti_spam_passed": False,
            "baseline_passed": False, "strict_gate_passed": False, "live_promotion": False,
            "strict": {"hits": strict_hits, "recall_lower_bound": strict_hits / n if n else None,
                       "bounds_scope": "observed public cohort only; undiscovered fills could reduce false positives",
                       "precision_lower_bound": strict_hits / p if p else None,
                       "f1_lower_bound": 2 * strict_hits / (n + p) if n + p else None,
                       "recall_upper_bound": upper_hits / n if n else None,
                       "precision_upper_bound": upper_hits / p if p else None,
                       "confirmed_false_positives_lower_bound": p - upper_hits,
                       "assignments": strict},
            "public_event_proxy": {"scope": "inferred public print time; not exact execution or private reaction",
                                   "hits": proxy_hits, "recall_all_observed_fills": proxy_hits / n if n else None,
                                   "precision_all_predictions": proxy_hits / p if p else None,
                                   "f1_all_observed_fills": 2 * proxy_hits / (n + p) if n + p else None,
                                   "unmatched_predictions": p - proxy_hits,
                                   "identified_fill_rows": proxy_identified,
                                   "linkage_coverage": proxy_identified / n if n else None,
                                   "recall_identifiable_subset": proxy_hits / proxy_identified if proxy_identified else None,
                                   "assignments": proxy},
            "unknown_execution_time_rows": n,
            "limitation": "Counts cover observed public rows, not a proven complete private execution history"}


def score_journal(directory: Path, *, cohort_start: float, cohort_end: float,
                  candidate_id: str) -> dict[str, Any]:
    """Explicit offline proxy audit. This cannot qualify or spend a holdout."""
    from .skipwatch_journal import iter_records

    start, end = _number(cohort_start), _number(cohort_end)
    if not 0 < end - start <= 86400 or start % 300 or end % 300:
        raise ResearchDataError("Cohort must be aligned five-minute windows, at most one day")
    valid_candidates = {row["id"] for row in PROTOCOL["grid"]}
    if candidate_id not in valid_candidates:
        raise ResearchDataError("Unknown preregistered candidate")
    fills: dict[str, dict[str, Any]] = {}
    associations: dict[str, dict[str, Any]] = {}
    recent_features: dict[int, dict[str, Any]] = {}
    predictions_by_candidate: dict[str, list[Prediction]] = {name: [] for name in (candidate_id, *BASELINES)}
    decision_bins: set[tuple[str, int]] = set()
    unclassified_fill_rows: set[str] = set()
    digest = hashlib.sha256()
    for record in iter_records(directory):
        kind, payload = record["kind"], record["payload"]
        if kind not in {"wallet_fill", "wallet_observation", "execution_prediction_batch", "opportunity"}:
            continue
        digest.update(_canonical({key: record[key] for key in ("seq", "kind", "at", "observed_at", "payload")}))
        if kind == "opportunity":
            recent_features[int(record["seq"])] = record
            if len(recent_features) > 128:
                del recent_features[min(recent_features)]
        elif kind == "wallet_fill":
            slug = str(payload.get("slug", ""))
            prefix = "btc-updown-5m-"
            if not slug.startswith(prefix) or not slug[len(prefix):].isdigit():
                if not slug or slug.startswith(prefix):
                    unclassified_fill_rows.add(str(payload["fill_id"]))
                continue
            window_start = int(slug[len(prefix):])
            if start <= window_start < end:
                identity = str(payload["fill_id"])
                normalized = {key: payload.get(key) for key in ("market_id", "side", "price", "size", "exchange_at", "action")}
                if identity in fills and fills[identity] != normalized:
                    raise ResearchDataError("Wallet row changed after observation")
                fills[identity] = normalized
        elif kind == "wallet_observation":
            window_start = payload.get("window_start")
            if window_start is None or not start <= _number(window_start) < end:
                continue
            identity = str(payload["fill_id"])
            old = associations.get(identity)
            if old is not None and old != payload:
                associations[identity] = {"ambiguous_revision": True}
            else:
                associations[identity] = payload
        elif payload.get("protocol_hash") == PROTOCOL_HASH and start <= _number(payload["window_start"]) < end:
            if _number(record["observed_at"]) < _number(payload["at"]):
                raise ResearchDataError("Prediction predates its journal record")
            if int(payload["feature_prefix_seq"]) >= int(record["seq"]):
                raise ResearchDataError("Prediction uses a future feature prefix")
            evidence = payload["feature_evidence"]
            if len(evidence) != 2 or {item["side"] for item in evidence} != {"up", "down"}:
                raise ResearchDataError("Prediction lacks paired feature evidence")
            for item in evidence:
                feature = recent_features.get(int(item["seq"]))
                if (feature is None or _digest(feature["payload"]) != item["hash"]
                        or feature["payload"].get("window") != payload["window"]
                        or int(item["seq"]) >= int(record["seq"])
                        or _number(feature["observed_at"]) > _number(payload["at"])
                        or not _valid_feature(feature["payload"], _number(payload["at"]))):
                    raise ResearchDataError("Prediction feature evidence is missing or noncausal")
            decision_bins.add((str(payload["window"]), int(payload["decision_bin"])))
            for item in payload["predictions"]:
                if item["candidate_id"] in predictions_by_candidate:
                    predictions_by_candidate[item["candidate_id"]].append(Prediction(
                        str(item["prediction_id"]), str(payload["window"]), str(item["side"]),
                        _number(item["price"]), _number(payload["at"])))
        if len(fills) > 250000 or len(associations) > 250000 or len(decision_bins) > 86400:
            raise ResearchDataError("Research cohort exceeds fixed evidence capacity")
    labels = []
    for identity, row in sorted(fills.items()):
        association = associations.get(identity, {})
        evidence = association.get("candidate_evidence", [])
        linked = (association.get("match_method") == "transaction_token_price_size"
                  and association.get("confidence") == "inferred" and len(evidence) == 1
                  and evidence[0].get("trade_id") is not None)
        labels.append(FillLabel(identity, str(row["market_id"]), str(row["side"]), _number(row["price"]),
                                _number(evidence[0]["at"]) if linked else None,
                                str(evidence[0]["trade_id"]) if linked else None,
                                action=str(row["action"]).lower() if str(row["action"]).lower() in {"buy", "sell"} else "unknown"))
    reports = {}
    for name in (candidate_id, *BASELINES):
        reports[name] = score(predictions_by_candidate[name], labels)
        unknown = len(unclassified_fill_rows)
        if unknown:
            report = reports[name]
            n, p = report["source_fill_rows"], report["predictions"]
            strict, proxy = report["strict"], report["public_event_proxy"]
            strict["recall_lower_bound"] = strict["hits"] / (n + unknown)
            strict["f1_lower_bound"] = 2 * strict["hits"] / (n + unknown + p)
            strict["recall_upper_bound"] = 1.0 if p else 0.0
            strict["precision_upper_bound"] = min(1.0, (strict["precision_upper_bound"] or 0)
                                                  + unknown / p) if p else None
            strict["confirmed_false_positives_lower_bound"] = max(
                0, strict["confirmed_false_positives_lower_bound"] - unknown)
            proxy["recall_known_cohort_rows"] = proxy["recall_all_observed_fills"]
            proxy["recall_all_observed_fills"] = proxy["f1_all_observed_fills"] = None
            proxy["recall_lower_bound_with_unknown_scope"] = proxy["hits"] / (n + unknown)
            report["all_source_fills_denominator"] = False
            report["source_fill_rows_upper_bound"] = n + unknown
    result = reports[candidate_id]
    result.update({"scope": "descriptive_proxy_audit_not_held_out", "cohort_start": start, "cohort_end": end,
                   "candidate_id": candidate_id, "input_digest": digest.hexdigest(),
                   "source_scope_unknown_fill_rows": len(unclassified_fill_rows),
                   "source_completeness_verified": False,
                   "eligible_decision_bins": len(decision_bins),
                   "expected_decision_bins": int(end - start),
                   "baselines": {key: value for key, value in reports.items() if key in BASELINES}})
    return result
