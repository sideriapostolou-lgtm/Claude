"""Conditional probability observer with its own prospective protocol and history.

No client, order, account, strategy or promotion interface. Official labels score
frozen forecasts before any bin update. Missing data is never a zero outcome.
"""
from __future__ import annotations

import copy
import hashlib
import json
import logging
import math
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .speeddesk_model import Window, fair_up

log = logging.getLogger("nightcrawler.kalshi_probability_learning")
PROTOCOL = "kalshi-probability-calibration-v2-h300-g5-b10-prior20"
HORIZON, GRACE, BINS, PRIOR = 300, 5, 10, 20
MAX_PENDING, MAX_RECENT, MAX_LABELS = 32, 64, 4096
SOURCE_FILES = ("kalshi_probability_learning.py", "speeddesk_model.py", "speeddesk_feeds.py",
                "speeddesk_kalshi.py", "speeddesk_kalshi_ws.py", "speeddesk_venues.py",
                "speeddesk.py", "kalshi_arena.py")
LABEL_TIMEOUT = 7200
ERROR_CODES = frozenset({"window_input_capacity", "label_input_capacity", "malformed_label_record",
                         "malformed_label_key", "conflicting_or_invalid_final_label",
                         "clock_invalid_or_reversed", "malformed_optional_learning_state",
                         "source_or_protocol_mismatch", "optional_learning_method_failed",
                         "source_fingerprint_unavailable", "arena_state_unreadable", "raw_stream_invalid"})
COUNTERS = ("forecasts", "scored", "unknown", "startup_inside", "late", "invalid", "pregap",
            "terms_changed", "missing_label", "outcome_known", "label_conflict", "invalid_label", "capacity",
            "invalid_batch", "invalid_strike")


def finite(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def terms(window: Window) -> list[Any]:
    return [window.start, window.end, window.start_price, window.venue_start_price,
            window.taker_coefficient, window.maker_coefficient, window.tick_size,
            window.min_trade_qty, window.fee_rounding, window.venue]



def valid_slug(value: Any) -> bool:
    return isinstance(value, str) and value.startswith("KXBTC15M-") and len(value) <= 128


def valid_gaps(values: Any) -> bool:
    return (isinstance(values, list) and len(values) <= 2 and len(set(values)) == len(values)
            and all(v in ("raw_stream_gap", "child_restart_gap") for v in values))


def valid_terms(values: Any) -> bool:
    """Only fixed, finite JSON shapes may enter optional checkpoint state."""
    return (isinstance(values, list) and len(values) == 10
            and all(finite(values[i]) for i in (0, 1, 4, 6, 7)) and values[1] - values[0] == 900
            and all(values[i] is None or (finite(values[i]) and values[i] > 0) for i in (2, 3))
            and (values[5] is None or finite(values[5]))
            and values[6] > 0 and values[7] > 0
            and values[8] in ("half_even", "kalshi") and values[9] == "kalshi")


def fingerprint() -> str:
    """Bind the observer, admission hooks, input qualification and shared fair model."""
    digest = hashlib.sha256(PROTOCOL.encode())
    for name in SOURCE_FILES:
        digest.update(name.encode())
        digest.update(Path(__file__).with_name(name).read_bytes())
    return digest.hexdigest()


class ProbabilityLearning:
    """Constant-size optional state. Only the arena child owns this object."""

    def __init__(self, started_at: float) -> None:
        try:
            self.source = fingerprint()
        except Exception:  # noqa: BLE001 - unavailable identity disables this observer only
            self.source = "0" * 64
        self.history_protocol, self.history_source = PROTOCOL, self.source
        clock_valid = finite(started_at)
        self.started_at = started_at if clock_valid else 0.0
        self.enabled = True
        self.error: str | None = None
        self.watermark = -1.0  # admission watermark, NEVER largest settled label
        self.last_at = self.started_at
        self.counts = dict.fromkeys(COUNTERS, 0)
        self.bin_n = [0] * BINS
        self.bin_wins = [0] * BINS
        self.brier_p = self.brier_q = 0.0
        self.pending: dict[str, dict[str, Any]] = {}
        self.recent: list[dict[str, Any]] = []
        self.labels: dict[str, dict[str, Any]] = {}
        self.batch_seq: int | None = None
        self.batch_dropped = 0
        self.batch_at: float | None = None
        self._staged_batch_at: float | None = None
        self.raw_gap_at: float | None = None
        self.restore_rejected = False
        if not clock_valid:
            self.disable("clock_invalid_or_reversed")
        if self.source == "0" * 64:
            self.disable("source_fingerprint_unavailable")

    def disable(self, reason: str) -> None:
        self.enabled, self.error = False, reason if reason in ERROR_CODES else "optional_learning_method_failed"

    def _event(self, event: str, now: float, **detail: Any) -> None:
        payload = {"at": now, "mode": "observe_only", "live_application": False,
                   "profitability_proven": False, "protocol": PROTOCOL,
                   "source_fingerprint": self.source, **detail}
        try:
            log.info("kalshi_probability_learning_%s %s", event,
                     json.dumps(payload, allow_nan=False, separators=(",", ":")))
        except Exception:  # noqa: BLE001, S110 - receipts cannot alter sampling or training
            pass

    def status(self, now: float) -> None:
        self._event("status", now, learning=self.panel())

    def _finish(self, slug: str, reason: str, now: float) -> None:
        row = self.pending.pop(slug)
        self.counts["unknown"] += 1
        self.counts[reason] += 1
        self.recent.append({"window": slug, "status": "unknown", "reason": reason,
                            "forecast": row.get("forecast"), "post_gaps": row["post_gaps"]})
        self.recent = self.recent[-MAX_RECENT:]
        self._event("unknown", now, window=slug, reason=reason)

    def discover(self, windows: Sequence[Window], now: float) -> None:
        if not self.enabled:
            return
        if not finite(now) or now < self.last_at:
            self.disable("clock_invalid_or_reversed")
            return
        if len(windows) > MAX_LABELS:
            self.disable("window_input_capacity")
            return
        for w in sorted(windows, key=lambda item: item.start):
            if w.slug in self.pending:
                row = self.pending[w.slug]
                current = terms(w)
                prior = row["terms"]
                if row["forecast"] is None:
                    # First known strikes complete missing metadata; never rewrite
                    # a known strike or reconstruct a forecast after an outcome.
                    for index in (2, 3):
                        if prior[index] is None and finite(current[index]) and current[index] > 0:
                            prior[index] = current[index]
                    row["opening"] = prior[2]
                if current != prior:
                    self._finish(w.slug, "terms_changed", now)
                continue
            if not w.slug.startswith("KXBTC15M-") or len(w.slug) > 128 or w.venue != "kalshi":
                continue
            if not finite(w.start) or not finite(w.end) or w.end - w.start != 900 or w.end <= self.started_at:
                continue
            if w.start <= self.watermark:
                continue
            self.watermark = w.start
            if len(self.pending) >= MAX_PENDING:
                self.counts["unknown"] += 1
                self.counts["capacity"] += 1
                continue
            copied_terms = terms(w)
            if not valid_terms(copied_terms):
                self.counts["unknown"] += 1
                self.counts["invalid"] += 1
                self._event("unknown", now, window=w.slug, reason="invalid")
                continue
            self.pending[w.slug] = {"start": w.start, "end": w.end, "opening": w.start_price,
                                    "terms": copied_terms, "pregap": None, "post_gaps": [], "forecast": None}
            if self.raw_gap_at is not None and self.raw_gap_at >= w.start:
                self.pending[w.slug]["pregap"] = "raw_stream_gap"
            if w.start <= self.started_at or now >= w.start:
                self._finish(w.slug, "startup_inside", now)

    def batch(self, message: Any, now: float) -> None:
        """Observe raw transport integrity before legacy coercion; ignore simulator gaps."""
        if not self.enabled:
            return
        if (not finite(now) or now < self.last_at or not isinstance(message, tuple)
                or len(message) != 6 or message[0] != "batch"):
            self.disable("raw_stream_invalid")
            return
        _, seq, sent_at, dropped, flush_us, records = message
        if (type(seq) is not int or not 1 <= seq <= 10**12 or type(dropped) is not int
                or not 0 <= dropped <= 10**12 or not finite(sent_at)
                or type(flush_us) is not int or flush_us < 0
                or not isinstance(records, (tuple, list)) or len(records) > MAX_LABELS
                or (self.batch_seq is not None and seq <= self.batch_seq)
                or dropped < self.batch_dropped):
            self.disable("raw_stream_invalid")
            return
        # A missing frame could conceal terms or a label, regardless of maker health.
        broken = (seq != (1 if self.batch_seq is None else self.batch_seq + 1)
                  or dropped > self.batch_dropped)
        for record in records:
            if (not isinstance(record, (tuple, list)) or not record or record[0] not in ("w", "k", "m", "o", "g", "b", "t")
                    or (record[0] in ("w", "k", "o") and len(record) != 2)
                    or (record[0] in ("m", "g") and len(record) != 4)):
                self.disable("raw_stream_invalid")
                return
        self.batch_seq, self.batch_dropped = seq, dropped
        self._staged_batch_at = sent_at
        self.last_at = now
        if broken:
            self.raw_gap_at = now
            for row in self.pending.values():
                if row["start"] <= now:
                    if row["forecast"] is None:
                        row["pregap"] = "raw_stream_gap"
                    elif "raw_stream_gap" not in row["post_gaps"]:
                        row["post_gaps"].append("raw_stream_gap")

    def batch_complete(self) -> None:
        """Only successful processing of every original record certifies a batch."""
        if self.enabled:
            self.batch_at = self._staged_batch_at
        self._staged_batch_at = None

    def labels_received(self, rows: Sequence[Any], now: float) -> None:
        """Validate ORIGINAL wire values before the arena's legacy bool coercion."""
        if not self.enabled:
            return
        if not finite(now) or now < self.last_at:
            self.disable("clock_invalid_or_reversed")
            return
        if len(rows) > MAX_LABELS:
            self.disable("label_input_capacity")
            return
        self.last_at = now
        for item in rows:
            if not isinstance(item, (tuple, list)) or len(item) != 2:
                self.disable("malformed_label_record")
                return
            slug, outcome = item
            if not isinstance(slug, str) or len(slug) > 128:
                self.disable("malformed_label_key")
                return
            self._cache_label(slug, outcome, now)

    def _cache_label(self, slug: str, outcome: Any, now: float) -> None:
        value = outcome if type(outcome) is bool else None
        if slug in self.labels:
            if self.labels[slug]["outcome"] is not value:
                self.counts["label_conflict"] += 1
                self.disable("conflicting_or_invalid_final_label")
            return
        self.labels[slug] = {"outcome": value, "received_at": now}
        while len(self.labels) > MAX_RECENT:
            key = next(key for key in self.labels if key not in self.pending)
            del self.labels[key]

    def _score(self, slug: str, now: float) -> None:
        label = self.labels[slug]
        outcome = label["outcome"]
        row = self.pending.get(slug)
        if row is None:
            return
        if outcome is None:
            self._finish(slug, "invalid_label", now)
            return
        if label["received_at"] > row["end"] + LABEL_TIMEOUT:
            self._finish(slug, "missing_label", now)
            return
        frozen = row["forecast"]
        if frozen is None or label["received_at"] < row["end"] or now < row["end"]:
            self._finish(slug, "outcome_known", now)
            return
        y = int(outcome)
        p, q, b = frozen["p"], frozen["q"], frozen["bin"]
        # Prequential: score the immutable prior predictions BEFORE updating.
        self.brier_p += (p - y) ** 2
        self.brier_q += (q - y) ** 2
        self.counts["scored"] += 1
        self.bin_n[b] += 1
        self.bin_wins[b] += y
        self.pending.pop(slug)
        receipt = {"window": slug, "status": "scored", "outcome": outcome,
                   "forecast": frozen, "post_gaps": row["post_gaps"], "scored_at": now}
        self.recent.append(receipt)
        self.recent = self.recent[-MAX_RECENT:]
        self._event("scored", now, **receipt)

    def advance(self, windows: Sequence[Window], spot: float | None, sigma: float | None,
                bitcoin_at: float | None, now: float) -> None:
        if not self.enabled:
            return
        if not finite(now) or now < self.last_at:
            self.disable("clock_invalid_or_reversed")
            return
        self.last_at = now
        self.discover(windows, now)  # compare terms BEFORE consuming any raw cached label
        for slug in list(self.pending):
            if slug in self.labels:
                self._score(slug, now)
        if not self.enabled:
            return
        for slug, row in list(self.pending.items()):
            if row["forecast"] is not None:
                if now > row["end"] + LABEL_TIMEOUT:
                    self._finish(slug, "missing_label", now)
                continue
            elapsed = now - row["start"]
            if elapsed < HORIZON:
                continue
            if elapsed > HORIZON + GRACE:
                self._finish(slug, "late", now)
                continue
            if row["pregap"]:
                self._finish(slug, "pregap", now)
                continue
            if self.batch_at is None or not 0 <= now - self.batch_at <= 3:
                self._finish(slug, "invalid_batch", now)
                continue
            opening, strike = row["opening"], row["terms"][3]
            if not finite(strike) or strike <= 0 or opening != strike:
                self._finish(slug, "invalid_strike", now)
                continue
            if (not all(finite(v) for v in (spot, sigma, bitcoin_at, opening))
                    or spot is None or sigma is None or bitcoin_at is None or opening is None
                    or spot <= 0 or opening <= 0 or sigma < 0 or not 0 <= now - bitcoin_at <= 3):
                self._finish(slug, "invalid", now)
                continue
            p = fair_up(spot, opening, sigma, row["end"] - now, settles_on_average=True)
            if p is None or not finite(p) or not 0 <= p <= 1:
                self._finish(slug, "invalid", now)
                continue
            b = min(BINS - 1, int(p * BINS))
            n = self.bin_n[b]
            q = (self.bin_wins[b] + PRIOR * p) / (n + PRIOR)
            frozen: dict[str, Any] = {"p": p, "q": q, "bin": b, "n": n, "wins": self.bin_wins[b], "at": now,
                               "spot": spot, "sigma": sigma, "bitcoin_at": bitcoin_at,
                               "opening": opening, "venue_start_price": strike, "batch_at": self.batch_at,
                               "terms": list(row["terms"]), "protocol": PROTOCOL, "source_fingerprint": self.source}
            row["forecast"] = frozen
            self.counts["forecasts"] += 1
            self._event("forecast", now, window=slug, **frozen)

    def panel(self) -> dict[str, Any]:
        n = self.counts["scored"]
        return {"mode": "observe_only", "enabled": self.enabled, "live_application": False,
                "profitability_proven": False, "protocol": PROTOCOL, "source_fingerprint": self.source,
                "history_protocol": self.history_protocol, "history_source_fingerprint": self.history_source,
                "forecast_horizon_s": HORIZON, "grace_s": GRACE, "bins": BINS,
                "pending": sum(row["forecast"] is not None for row in self.pending.values()), **{k: self.counts[k] for k in ("forecasts", "scored", "unknown")},
                "brier_baseline": self.brier_p / n if n else None,
                "brier_shadow": self.brier_q / n if n else None, "error": self.error,
                "coverage": "conditional fresh-input probabilities; continuous coverage and profitability not certified",
                "exclusions": {k: self.counts[k] for k in ("startup_inside", "late", "invalid", "pregap",
                    "terms_changed", "missing_label", "outcome_known", "invalid_label", "capacity",
                    "invalid_batch", "invalid_strike")}}

    def state(self) -> dict[str, Any]:
        return copy.deepcopy({"protocol": self.history_protocol, "source_fingerprint": self.history_source,
                "enabled": self.enabled, "error": self.error, "watermark": self.watermark, "last_at": self.last_at,
                "counts": self.counts, "bin_n": self.bin_n, "bin_wins": self.bin_wins,
                "brier_p": self.brier_p, "brier_q": self.brier_q, "pending": self.pending,
                "recent": self.recent, "labels": self.labels, "restore_rejected": self.restore_rejected})

    def restore(self, raw: Any, now: float) -> None:
        if raw is None:
            return
        try:
            self._restore(raw, now)
        except Exception:  # noqa: BLE001 - optional corruption must never reset the arena
            self.restore_rejected = True
            self.disable("malformed_optional_learning_state")

    def _restore(self, raw: Any, now: float) -> None:
        if not isinstance(raw, dict) or set(raw) != set(self.state()) or not finite(now):
            raise ValueError("state shape")
        if len(json.dumps(raw, allow_nan=False)) > 262144:
            raise ValueError("state capacity")
        protocol, source = raw["protocol"], raw["source_fingerprint"]
        if (not isinstance(protocol, str) or len(protocol) > 80 or not isinstance(source, str)
                or len(source) != 64 or set(source) - set("0123456789abcdef")):
            raise ValueError("history identity")
        mismatch = protocol != PROTOCOL or source != self.source
        counts = raw["counts"]
        if (not isinstance(counts, dict) or set(counts) != set(COUNTERS)
                or any(type(v) is not int or not 0 <= v <= 10**12 for v in counts.values())):
            raise ValueError("counts")
        exclusions = set(COUNTERS) - {"forecasts", "scored", "unknown", "label_conflict"}
        if counts["unknown"] != sum(counts[k] for k in exclusions):
            raise ValueError("unknown counts")
        bn, bw = raw["bin_n"], raw["bin_wins"]
        if (not isinstance(bn, list) or not isinstance(bw, list) or len(bn) != BINS or len(bw) != BINS
                or any(type(n) is not int or type(w) is not int or not 0 <= w <= n <= 10**12
                       for n, w in zip(bn, bw, strict=True)) or sum(bn) != counts["scored"]):
            raise ValueError("bins")
        if any(not finite(raw[k]) for k in ("watermark", "last_at", "brier_p", "brier_q")):
            raise ValueError("numeric state")
        if now < raw["last_at"] or any(not 0 <= raw[k] <= counts["scored"] for k in ("brier_p", "brier_q")):
            raise ValueError("scores/clock")
        pending, recent, labels = raw["pending"], raw["recent"], raw["labels"]
        if (not isinstance(pending, dict) or len(pending) > MAX_PENDING or not isinstance(recent, list)
                or len(recent) > MAX_RECENT or not isinstance(labels, dict) or len(labels) > MAX_RECENT):
            raise ValueError("retention")
        for slug, row in pending.items():
            self._validate_row(slug, row, raw, bn, bw, mismatch)
        receipt_slugs: set[str] = set()
        retained_scored = retained_unknown = retained_unknown_frozen = 0
        for receipt in recent:
            if (not isinstance(receipt, dict) or not valid_slug(receipt.get("window"))
                    or receipt.get("status") not in ("unknown", "scored")
                    or not valid_gaps(receipt.get("post_gaps"))):
                raise ValueError("receipt")
            if receipt["window"] in receipt_slugs or receipt["window"] in pending:
                raise ValueError("duplicate terminal window")
            receipt_slugs.add(receipt["window"])
            frozen = receipt.get("forecast")
            if frozen is not None:
                self._validate_forecast(frozen, frozen.get("terms"), raw, bn, bw, mismatch)
            if receipt["status"] == "unknown":
                retained_unknown += 1
                retained_unknown_frozen += int(frozen is not None)
                if set(receipt) != {"window", "status", "reason", "forecast", "post_gaps"} or receipt["reason"] not in exclusions:
                    raise ValueError("unknown receipt")
            elif (set(receipt) != {"window", "status", "outcome", "forecast", "post_gaps", "scored_at"}
                  or type(receipt["outcome"]) is not bool or frozen is None or not finite(receipt["scored_at"])
                  or not frozen["terms"][1] <= receipt["scored_at"] <= raw["last_at"]):
                raise ValueError("scored receipt")
            else:
                retained_scored += 1
        if counts["unknown"] < retained_unknown or counts["scored"] < retained_scored:
            raise ValueError("retained receipt counts")
        for slug, label in labels.items():
            if (not isinstance(slug, str) or len(slug) > 128 or not isinstance(label, dict)
                    or set(label) != {"outcome", "received_at"}
                    or (type(label["outcome"]) is not bool and label["outcome"] is not None)
                    or not finite(label["received_at"]) or label["received_at"] > raw["last_at"]):
                raise ValueError("labels")
        if counts["forecasts"] < (counts["scored"] + retained_unknown_frozen
                                  + sum(r["forecast"] is not None for r in pending.values())):
            raise ValueError("forecast counts")
        if (type(raw["enabled"]) is not bool or type(raw["restore_rejected"]) is not bool
                or (raw["error"] is not None and raw["error"] not in ERROR_CODES)
                or (raw["enabled"] and raw["error"] is not None)):
            raise ValueError("status")
        # Only validated old state is committed. A source change preserves counts,
        # disables this observer and cannot merge histories or migrate V1.
        saved = copy.deepcopy(raw)
        self.history_protocol, self.history_source = protocol, source
        self.counts, self.bin_n, self.bin_wins = saved["counts"], saved["bin_n"], saved["bin_wins"]
        self.brier_p, self.brier_q = saved["brier_p"], saved["brier_q"]
        self.pending, self.recent, self.labels = saved["pending"], saved["recent"], saved["labels"]
        self.watermark, self.last_at = saved["watermark"], now
        self.enabled, self.error, self.restore_rejected = saved["enabled"], saved["error"], saved["restore_rejected"]
        if mismatch:
            self.disable("source_or_protocol_mismatch")
        elif self.enabled:
            for slug, row in list(self.pending.items()):
                if row["forecast"] is None and row["start"] <= now:
                    self._finish(slug, "startup_inside", now)
                elif row["forecast"] is not None and "child_restart_gap" not in row["post_gaps"]:
                    row["post_gaps"].append("child_restart_gap")

    def _validate_row(self, slug: Any, row: Any, raw: dict[str, Any], bn: list[int], bw: list[int], mismatch: bool) -> None:
        if (not valid_slug(slug) or not isinstance(row, dict)
                or set(row) != {"start", "end", "opening", "terms", "pregap", "post_gaps", "forecast"}
                or not finite(row["start"]) or not finite(row["end"]) or row["end"] - row["start"] != 900
                or row["start"] > raw["watermark"] or not valid_terms(row["terms"])
                or row["terms"][:2] != [row["start"], row["end"]] or row["opening"] != row["terms"][2]
                or row["pregap"] not in (None, "raw_stream_gap")
                or not valid_gaps(row["post_gaps"])):
            raise ValueError("pending")
        if row["forecast"] is not None:
            if row["pregap"] is not None:
                raise ValueError("forecast after preforecast raw gap")
            self._validate_forecast(row["forecast"], row["terms"], raw, bn, bw, mismatch)

    def _validate_forecast(self, f: Any, pinned: Any, raw: dict[str, Any], bn: list[int], bw: list[int], mismatch: bool) -> None:
        if (not isinstance(f, dict) or set(f) != {"p", "q", "bin", "n", "wins", "at", "spot", "sigma",
                                               "bitcoin_at", "opening", "venue_start_price", "batch_at", "terms",
                                               "protocol", "source_fingerprint"}
                or not valid_terms(pinned) or f["terms"] != pinned
                or not all(finite(f[k]) for k in ("p", "q", "at", "spot", "sigma", "bitcoin_at", "opening", "venue_start_price", "batch_at"))
                or not 0 <= f["p"] <= 1 or not 0 <= f["q"] <= 1 or f["spot"] <= 0 or f["sigma"] < 0
                or not f["opening"] == f["venue_start_price"] == pinned[2] == pinned[3] or f["opening"] <= 0
                or type(f["bin"]) is not int or f["bin"] != min(BINS - 1, int(f["p"] * BINS))
                or type(f["n"]) is not int or type(f["wins"]) is not int or not 0 <= f["wins"] <= f["n"] <= 10**12
                or f["n"] > bn[f["bin"]] or f["wins"] > bw[f["bin"]]
                or f["n"] - f["wins"] > bn[f["bin"]] - bw[f["bin"]]
                or not pinned[0] + HORIZON <= f["at"] <= pinned[0] + HORIZON + GRACE
                or f["at"] > raw["last_at"] or not 0 <= f["at"] - f["bitcoin_at"] <= 3
                or not 0 <= f["at"] - f["batch_at"] <= 3
                or f["protocol"] != raw["protocol"] or f["source_fingerprint"] != raw["source_fingerprint"]
                or f["q"] != (f["wins"] + PRIOR * f["p"]) / (f["n"] + PRIOR)):
            raise ValueError("frozen forecast")
        if not mismatch and f["p"] != fair_up(f["spot"], f["opening"], f["sigma"], pinned[1] - f["at"], settles_on_average=True):
            raise ValueError("forecast model")
