"""Bounded child-only, observe-only prequential probability calibration.

No client, order, account, strategy or promotion interface. Official labels score
frozen forecasts before any bin update. Missing data is never a zero outcome.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .speeddesk_model import Window, fair_up

log = logging.getLogger("nightcrawler.kalshi_online_learning")
PROTOCOL = "kalshi-online-calibration-v1-h300-g5-b10-prior20"
HORIZON, GRACE, BINS, PRIOR = 300, 5, 10, 20
MAX_PENDING, MAX_RECENT, MAX_LABELS = 32, 64, 4096
LABEL_TIMEOUT = 7200
ERROR_CODES = frozenset({"window_input_capacity", "label_input_capacity", "malformed_label_record",
                         "malformed_label_key", "conflicting_or_invalid_final_label",
                         "clock_invalid_or_reversed", "malformed_optional_learning_state",
                         "source_or_protocol_mismatch", "optional_learning_method_failed",
                         "source_fingerprint_unavailable", "arena_state_unreadable"})
COUNTERS = ("forecasts", "scored", "unknown", "startup_inside", "late", "invalid", "pregap",
            "terms_changed", "missing_label", "outcome_known", "label_conflict", "invalid_label", "capacity")


def finite(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def terms(window: Window) -> list[Any]:
    return [window.start, window.end, window.start_price, window.venue_start_price,
            window.taker_coefficient, window.maker_coefficient, window.tick_size,
            window.min_trade_qty, window.fee_rounding, window.venue]



def valid_terms(values: list[Any]) -> bool:
    """Only fixed, finite JSON shapes may enter optional checkpoint state."""
    return (len(values) == 10 and all(finite(values[i]) for i in (0, 1, 4, 6, 7))
            and all(values[i] is None or (finite(values[i]) and values[i] > 0) for i in (2, 3))
            and (values[5] is None or finite(values[5]))
            and values[6] > 0 and values[7] > 0
            and values[8] in ("half_even", "kalshi") and values[9] == "kalshi")


def fingerprint() -> str:
    return hashlib.sha256(PROTOCOL.encode() + Path(__file__).read_bytes()
                          + Path(fair_up.__code__.co_filename).read_bytes()).hexdigest()


class OnlineLearning:
    """Constant-size optional state. Only the arena child owns this object."""

    def __init__(self, started_at: float) -> None:
        try:
            self.source = fingerprint()
        except OSError:
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
        self.feed_ok: bool | None = None
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
        log.info("kalshi_online_learning_%s %s", event,
                 json.dumps(payload, allow_nan=False, separators=(",", ":")))

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
            if w.start < self.started_at or now > w.start:
                self._finish(w.slug, "startup_inside", now)

    def degrade(self, slug: str, reason: str, now: float) -> None:
        if not self.enabled or slug not in self.pending:
            return
        row = self.pending[slug]
        if row["start"] <= now:
            if row["forecast"] is None:
                row["pregap"] = reason[:80]
            elif reason not in row["post_gaps"]:
                row["post_gaps"] = (row["post_gaps"] + [reason[:80]])[:8]

    def gap(self, slugs: Sequence[str], trade_stream: bool, coinbase: bool, now: float) -> None:
        if not self.enabled:
            return
        self.feed_ok = trade_stream and coinbase
        selected = set(slugs[:MAX_LABELS])
        for slug, row in self.pending.items():
            if row["start"] <= now < row["end"] and (not self.feed_ok or slug in selected):
                if row["forecast"] is None:
                    row["pregap"] = "explicit_feed_gap"
                elif "explicit_feed_gap" not in row["post_gaps"]:
                    row["post_gaps"].append("explicit_feed_gap")

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
                bitcoin_at: float | None, outcomes: Mapping[str, Any], now: float,
                degraded: Mapping[str, str], terms_checked: bool = False) -> None:
        if not self.enabled:
            return
        if not finite(now) or now < self.last_at:
            self.disable("clock_invalid_or_reversed")
            return
        self.last_at = now
        if not terms_checked:
            self.discover(windows, now)  # compare terms BEFORE consuming any cached label
        # Only bounded pending keys are looked up; no historical outcome scan.
        for slug in list(self.pending):
            if slug in outcomes and slug not in self.labels:
                self._cache_label(slug, outcomes[slug], now)
            if slug in self.labels:
                self._score(slug, now)
        if not self.enabled:
            return
        for slug, row in list(self.pending.items()):
            if row["forecast"] is not None:
                if slug in degraded and degraded[slug] not in row["post_gaps"]:
                    row["post_gaps"].append(degraded[slug][:80])
                    row["post_gaps"] = row["post_gaps"][:8]
                if now > row["end"] + LABEL_TIMEOUT:
                    self._finish(slug, "missing_label", now)
                continue
            elapsed = now - row["start"]
            if elapsed < HORIZON:
                continue
            if elapsed > HORIZON + GRACE:
                self._finish(slug, "late", now)
                continue
            if row["pregap"] or slug in degraded or self.feed_ok is False:
                self._finish(slug, "pregap", now)
                continue
            opening = row["opening"]
            if (not all(finite(v) for v in (spot, sigma, bitcoin_at, opening))
                    or spot is None or sigma is None or bitcoin_at is None or opening is None
                    or spot <= 0 or opening <= 0 or sigma < 0 or not 0 <= now - bitcoin_at <= 3):
                self._finish(slug, "invalid", now)
                continue
            p = fair_up(spot, opening, sigma, row["end"] - now, settles_on_average=True)
            if p is None:
                self._finish(slug, "invalid", now)
                continue
            b = min(BINS - 1, int(p * BINS))
            n = self.bin_n[b]
            q = (self.bin_wins[b] + PRIOR * p) / (n + PRIOR)
            frozen: dict[str, Any] = {"p": p, "q": q, "bin": b, "n": n, "wins": self.bin_wins[b], "at": now,
                               "spot": spot, "sigma": sigma, "bitcoin_at": bitcoin_at,
                               "opening": opening, "venue_start_price": row["terms"][3],
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
                "coverage": "quiet observations; full data coverage not certified",
                "exclusions": {k: self.counts[k] for k in ("startup_inside", "late", "invalid", "pregap",
                    "terms_changed", "missing_label", "outcome_known", "invalid_label", "capacity")}}

    def state(self) -> dict[str, Any]:
        return {"protocol": self.history_protocol, "source_fingerprint": self.history_source, "enabled": self.enabled,
                "error": self.error, "watermark": self.watermark, "last_at": self.last_at,
                "counts": dict(self.counts), "bin_n": list(self.bin_n), "bin_wins": list(self.bin_wins),
                "brier_p": self.brier_p, "brier_q": self.brier_q, "pending": self.pending,
                "recent": self.recent, "labels": self.labels, "feed_ok": self.feed_ok,
                "restore_rejected": self.restore_rejected}

    def restore(self, raw: Any, now: float) -> None:
        if raw is None:
            return
        try:
            self._restore(raw, now)
        except Exception:  # noqa: BLE001 - optional corruption must never reset the arena
            self.restore_rejected = True
            self.disable("malformed_optional_learning_state")

    def _restore(self, raw: Any, now: float) -> None:
        if not isinstance(raw, dict) or len(raw) > 24:
            raise ValueError("state shape")
        if len(json.dumps(raw, allow_nan=False)) > 131072:
            raise ValueError("state capacity")
        mismatch = raw["protocol"] != PROTOCOL or raw["source_fingerprint"] != self.source
        if (not isinstance(raw["protocol"], str) or len(raw["protocol"]) > 80
                or not isinstance(raw["source_fingerprint"], str) or len(raw["source_fingerprint"]) != 64
                or set(raw["source_fingerprint"]) - set("0123456789abcdef")):
            raise ValueError("history identity")
        counts = raw["counts"]
        if set(counts) != set(COUNTERS) or any(type(v) is not int or not 0 <= v <= 10**12 for v in counts.values()):
            raise ValueError("counts")
        bn, bw = raw["bin_n"], raw["bin_wins"]
        if (len(bn) != BINS or len(bw) != BINS or any(type(n) is not int or not 0 <= w <= n <= 10**12
                or type(w) is not int for n, w in zip(bn, bw, strict=True)) or sum(bn) != counts["scored"]):
            raise ValueError("bins")
        if any(not finite(raw[k]) for k in ("watermark", "last_at", "brier_p", "brier_q")):
            raise ValueError("numeric state")
        if any(not 0 <= raw[k] <= counts["scored"] for k in ("brier_p", "brier_q")):
            raise ValueError("scores")
        pending, recent, labels = raw["pending"], raw["recent"], raw["labels"]
        if not isinstance(pending, dict) or len(pending) > MAX_PENDING or len(recent) > MAX_RECENT or len(labels) > MAX_RECENT:
            raise ValueError("retention")
        for slug, r in pending.items():
            if not isinstance(slug, str) or not slug.startswith("KXBTC15M-") or not isinstance(r, dict):
                raise ValueError("pending")
            if not finite(r["start"]) or not finite(r["end"]) or r["end"] - r["start"] != 900 or r["start"] > raw["watermark"]:
                raise ValueError("pending bounds")
            if not isinstance(r["terms"], list) or not valid_terms(r["terms"]) or not isinstance(r["post_gaps"], list) or len(r["post_gaps"]) > 8:
                raise ValueError("terms/gaps")
            f = r["forecast"]
            if f is not None and (not isinstance(f, dict) or not all(finite(f[k]) for k in ("p", "q", "at", "spot", "sigma", "bitcoin_at", "opening"))
                    or not 0 <= f["p"] <= 1 or not 0 <= f["q"] <= 1 or type(f["bin"]) is not int or not 0 <= f["bin"] < BINS
                    or type(f["n"]) is not int or f["n"] < 0 or not r["start"] + HORIZON <= f["at"] <= r["start"] + HORIZON + GRACE):
                raise ValueError("forecast")
            if f is not None and (type(f.get("wins")) is not int or not 0 <= f["wins"] <= f["n"]
                    or f["n"] > bn[f["bin"]] or f["wins"] > bw[f["bin"]]
                    or f["n"] - f["wins"] > bn[f["bin"]] - bw[f["bin"]]):
                raise ValueError("forecast counts exceed retained history")
            if f is not None and not mismatch:
                expected = fair_up(f["spot"], f["opening"], f["sigma"], r["end"] - f["at"], settles_on_average=True)
                if (f["protocol"] != raw["protocol"] or f["source_fingerprint"] != raw["source_fingerprint"]
                        or f["terms"] != r["terms"] or f["opening"] != r["opening"]
                        or f["bin"] != min(9, int(f["p"] * 10)) or type(f["wins"]) is not int
                        or not 0 <= f["wins"] <= f["n"] or f["p"] != expected
                        or f["q"] != (f["wins"] + PRIOR * f["p"]) / (f["n"] + PRIOR)
                        or not 0 <= f["at"] - f["bitcoin_at"] <= 3):
                    raise ValueError("frozen forecast evidence")
        if counts["forecasts"] < counts["scored"] + sum(r["forecast"] is not None for r in pending.values()):
            raise ValueError("forecast counts")
        if type(raw["enabled"]) is not bool or (raw["error"] is not None and raw["error"] not in ERROR_CODES):
            raise ValueError("status")
        if raw["feed_ok"] is not None and type(raw["feed_ok"]) is not bool:
            raise ValueError("feed state")
        if not isinstance(recent, list) or any(not isinstance(item, dict) for item in recent):
            raise ValueError("recent")
        if not isinstance(labels, dict) or any(not isinstance(v, dict) or (type(v.get("outcome")) is not bool and v.get("outcome") is not None) or not finite(v.get("received_at")) for v in labels.values()):
            raise ValueError("labels")
        # Commit optional state only after validation. Preserve valid old counts
        # on a source/protocol mismatch, then disable instead of mixing versions.
        self.history_protocol, self.history_source = raw["protocol"], raw["source_fingerprint"]
        self.counts, self.bin_n, self.bin_wins = dict(counts), list(bn), list(bw)
        self.brier_p, self.brier_q = raw["brier_p"], raw["brier_q"]
        self.pending, self.recent, self.labels = pending, recent, labels
        self.watermark, self.last_at = raw["watermark"], max(now, raw["last_at"])
        self.feed_ok, self.enabled, self.error = raw["feed_ok"], raw["enabled"], raw["error"]
        self.restore_rejected = bool(raw.get("restore_rejected"))
        if mismatch:
            self.disable("source_or_protocol_mismatch")
        elif self.enabled:
            # No reconstruction after a child restart inside an admitted window.
            # Only already-frozen, pre-outcome predictions survive as scoreable.
            for slug, row in list(self.pending.items()):
                if row["forecast"] is None and row["start"] < now:
                    self._finish(slug, "startup_inside", now)
                elif row["forecast"] is not None and "child_restart_gap" not in row["post_gaps"]:
                    row["post_gaps"] = (row["post_gaps"][:7] + ["child_restart_gap"])
