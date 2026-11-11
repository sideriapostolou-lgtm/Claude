"""Child-only lineage for separate prospective probability measurement epochs.

Old raw checkpoints are frozen before validation/restart can annotate them. The
active learner keeps its strict restore rules; archives never receive callbacks.
"""
from __future__ import annotations

import contextlib
import copy
import hashlib
import json
import logging
from typing import Any

from .kalshi_probability_learning import PROTOCOL, ProbabilityLearning, finite

SCHEMA = 1
MAX_ARCHIVES, MAX_BYTES, MAX_STATE_BYTES = 4, 2 * 1024 * 1024, 262144
HOST_ERRORS = frozenset({"epoch_state_invalid", "epoch_history_missing", "epoch_history_disabled",
                         "epoch_protocol_unsupported", "epoch_capacity", "epoch_method_failed"})
LEGACY, EPOCHS = "learning_probability", "learning_probability_epochs"
MARKER = "learning_probability_epoch_schema"
log = logging.getLogger("nightcrawler.kalshi_probability_epochs")


def encoded(raw: Any) -> bytes:
    return json.dumps(raw, sort_keys=True, allow_nan=False, separators=(",", ":")).encode()


def digest(raw: Any) -> str:
    return hashlib.sha256(encoded(raw)).hexdigest()


def _eligible(raw: dict[str, Any]) -> bool:
    return (raw["restore_rejected"] is False and
            ((raw["enabled"] is True and raw["error"] is None) or
             (raw["enabled"] is False and raw["error"] == "source_or_protocol_mismatch")))


class _ValidationProbe(ProbabilityLearning):
    def _event(self, event: str, now: float, **detail: Any) -> None:
        """Validation annotations are never real observation receipts."""


class ProbabilityEpochs:
    """Startup/checkpoint host only; the arena retains the active learner pointer."""

    def __init__(self, active: ProbabilityLearning, now: float) -> None:
        self.active = active
        self.error: str | None = None
        self._legacy: dict[str, Any] | None = None
        self._envelope: dict[str, Any] | None = None
        try:
            raw = active.state()
            self._validate_state(raw, now)
            self._legacy = copy.deepcopy(raw)
            self._envelope = self._base(self._record(raw, 0, now))
            self._budget(self._envelope)
        except Exception:  # noqa: BLE001 - optional construction cannot affect the arena
            self._fail("epoch_state_invalid")

    def _validate_state(self, raw: Any, now: float) -> None:
        if not isinstance(raw, dict) or len(encoded(raw)) > MAX_STATE_BYTES:
            raise ValueError("epoch learner state")
        probe = _ValidationProbe(now)
        # Validation-only same-package coupling: public restore swallows malformed
        # input into restore_rejected, indistinguishable from a valid saved latch.
        # The unchanged strict implementation validates a disposable probe only.
        probe._restore(raw, now)
        if (probe.history_source != raw["source_fingerprint"] or
                probe.history_protocol != raw["protocol"]):
            raise ValueError("epoch learner identity")

    def _record(self, raw: dict[str, Any], ordinal: int, opened_at: float | None) -> dict[str, Any]:
        return {"ordinal": ordinal, "source_fingerprint": raw["source_fingerprint"],
                "protocol": raw["protocol"], "opened_at": opened_at,
                "state": copy.deepcopy(raw), "state_sha256": digest(raw)}

    def _base(self, active: dict[str, Any] | None) -> dict[str, Any]:
        return {"schema": SCHEMA, "legacy_sha256": digest(self._legacy),
                "archived": [], "active": active, "error": None}

    def _budget(self, envelope: dict[str, Any]) -> None:
        # Reserve the longest fixed latch, so a later refusal itself always fits.
        reserved = {**envelope, "error": max(HOST_ERRORS, key=len)}
        if (len(envelope["archived"]) > MAX_ARCHIVES or
                len(encoded({LEGACY: self._legacy, EPOCHS: reserved, MARKER: SCHEMA})) > MAX_BYTES):
            raise OverflowError("epoch retention capacity")

    def _fail(self, reason: str) -> None:
        self.error = reason if reason in HOST_ERRORS else "epoch_method_failed"
        if self._envelope is not None:
            self._envelope["error"] = self.error
        with contextlib.suppress(Exception):
            self.active.disable("malformed_optional_learning_state")

    def _validate_record(self, raw: Any, ordinal: int, now: float, *, archived: bool) -> None:
        keys = {"ordinal", "source_fingerprint", "protocol", "opened_at", "state", "state_sha256"}
        if archived:
            keys.add("closed_at")
        if (not isinstance(raw, dict) or set(raw) != keys or type(raw["ordinal"]) is not int
                or raw["ordinal"] != ordinal or raw["protocol"] != PROTOCOL):
            raise ValueError("epoch record")
        self._validate_state(raw["state"], now)
        if (raw["source_fingerprint"] != raw["state"]["source_fingerprint"] or
                raw["protocol"] != raw["state"]["protocol"] or raw["state_sha256"] != digest(raw["state"])):
            raise ValueError("epoch record identity/digest")
        opened = raw["opened_at"]
        if opened is None:
            if ordinal != 0 or raw["state"] != self._legacy:
                raise ValueError("epoch imported legacy")
        elif not finite(opened) or not 0 <= opened <= raw["state"]["last_at"]:
            raise ValueError("epoch opening time")
        if archived:
            closed = raw["closed_at"]
            if not finite(closed) or not max(0, raw["state"]["last_at"]) <= closed <= now:
                raise ValueError("epoch closing time")

    def restore(self, arena: dict[str, Any], now: float) -> None:
        """A loaded file is never a fresh bootstrap, including absent/null fields."""
        self._legacy, self._envelope, self.error = None, None, None
        try:
            legacy = arena.get(LEGACY)
            self._validate_state(legacy, now)
            assert isinstance(legacy, dict)
            self._legacy = copy.deepcopy(legacy)  # retain only validated, JSON-safe raw
            self._envelope = {**self._base(None), "error": "epoch_state_invalid"}
            # A separate atomic marker distinguishes damaged new checkpoints from
            # genuine pre-host history. Removing both is not detectable here.
            if EPOCHS not in arena:
                if MARKER in arena:
                    raise ValueError("epoch missing envelope")
                if legacy["protocol"] != PROTOCOL:
                    self._fail("epoch_protocol_unsupported")
                    return
                self._envelope = self._base(self._record(legacy, 0, None))
            else:
                raw = arena[EPOCHS]
                if (not isinstance(raw, dict) or type(raw.get("schema")) is not int or raw["schema"] != SCHEMA
                        or raw.get("legacy_sha256") != digest(legacy) or not isinstance(raw.get("archived"), list)):
                    raise ValueError("epoch envelope")
                for index, record in enumerate(raw["archived"][:MAX_ARCHIVES + 1]):
                    if index == MAX_ARCHIVES:
                        raise OverflowError("epoch archive capacity")
                    self._validate_record(record, index, now, archived=True)
                    if index and (record["opened_at"] is None or
                                  record["opened_at"] < raw["archived"][index - 1]["closed_at"]):
                        raise ValueError("epoch chronology")
                    prefix = {**self._envelope, "archived": [*self._envelope["archived"], copy.deepcopy(record)]}
                    self._budget(prefix)
                    self._envelope = prefix  # only the completely validated contiguous prefix
                # Validate activation metadata after salvaging certified archives.
                if (set(raw) != {"schema", "legacy_sha256", "archived", "active", "error"}
                        or type(arena.get(MARKER)) is not int or arena[MARKER] != SCHEMA
                        or (raw["error"] is not None and raw["error"] not in HOST_ERRORS)):
                    raise ValueError("epoch activation metadata")
                active = raw["active"]
                if active is None:
                    if raw["error"] is None:
                        raise ValueError("epoch missing active")
                else:
                    self._validate_record(active, len(raw["archived"]), now, archived=False)
                    if raw["archived"] and (active["opened_at"] is None or
                                            active["opened_at"] < raw["archived"][-1]["closed_at"]):
                        raise ValueError("epoch chronology")
                self._budget(raw)
                self._envelope = copy.deepcopy(raw)
            active = self._envelope["active"]
            if self._envelope["error"] is not None:
                self._fail(self._envelope["error"])
            elif not _eligible(active["state"]):
                self._fail("epoch_history_disabled")
            elif not self.active.enabled:
                self._fail("epoch_method_failed")
            elif active["source_fingerprint"] == self.active.source:
                self.active.restore(active["state"], now)
                if active["opened_at"] is None:
                    active["opened_at"] = now
                self.checkpoint()
            else:
                self._rollover(now)
        except OverflowError:
            self._fail("epoch_capacity")
        except Exception:  # noqa: BLE001 - bad optional history must never reset the arena
            self._fail("epoch_history_missing" if LEGACY not in arena and EPOCHS not in arena
                       else "epoch_state_invalid")

    def _rollover(self, now: float) -> None:
        assert self._envelope is not None
        prior = self._envelope["active"]
        candidate = {**self._envelope,
                     "archived": [*self._envelope["archived"], {**prior, "closed_at": now}],
                     "active": self._record(self.active.state(), prior["ordinal"] + 1, now)}
        self._budget(candidate)
        self._envelope = candidate

    def checkpoint(self) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        """Atomic bounded optional snapshot; refusal retains the last safe records."""
        if self._envelope is not None and self.error is None:
            try:
                raw = self.active.state()
                self._validate_state(raw, self.active.last_at)
                if (raw["source_fingerprint"] != self._envelope["active"]["source_fingerprint"]
                        or raw["source_fingerprint"] != self.active.source or raw["protocol"] != PROTOCOL):
                    raise ValueError("epoch active identity")
                record = {**self._envelope["active"], "state": raw, "state_sha256": digest(raw)}
                candidate = {**self._envelope, "active": record}
                self._budget(candidate)
                self._envelope = candidate
            except OverflowError:
                self._fail("epoch_capacity")
            except Exception:  # noqa: BLE001 - even malformed optional memory cannot poison arena JSON
                self._fail("epoch_method_failed")
        return self.retained_state()

    def retained_state(self) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        return copy.deepcopy(self._legacy), copy.deepcopy(self._envelope)

    @staticmethod
    def _summary(record: dict[str, Any]) -> dict[str, Any]:
        raw = record["state"]
        n = raw["counts"]["scored"]
        return {key: record[key] for key in ("ordinal", "protocol", "source_fingerprint", "opened_at")} | {
            "closed_at": record.get("closed_at"), "forecasts": raw["counts"]["forecasts"], "scored": n,
            "unknown": raw["counts"]["unknown"],
            "pending": sum(row["forecast"] is not None for row in raw["pending"].values()),
            "brier_baseline": raw["brier_p"] / n if n else None,
            "brier_shadow": raw["brier_q"] / n if n else None,
            "pending_frozen_unresolved": True}

    def current_panel(self) -> dict[str, Any] | None:
        if self.error is not None or self._envelope is None:
            return None
        try:
            panel = self.active.panel()
            if (panel["history_source_fingerprint"] != panel["source_fingerprint"] or
                    panel["history_protocol"] != panel["protocol"]):
                raise ValueError("epoch current panel identity")
            return panel
        except Exception:  # noqa: BLE001 - optional panel failures cannot prevent arena saves
            self._fail("epoch_method_failed")
            return None

    def panel(self) -> dict[str, Any]:
        envelope = self._envelope
        return {"schema": SCHEMA, "mode": "observe_only", "live_application": False,
                "profitability_proven": False, "error": self.error,
                "current_source_fingerprint": self.active.source,
                "active_ordinal": envelope["active"]["ordinal"] if envelope and envelope["active"] else None,
                "current_available": self.error is None and envelope is not None and envelope["active"] is not None,
                "archived": [self._summary(record) for record in envelope["archived"]] if envelope else [],
                "retained_active": self._summary(envelope["active"]) if envelope and envelope["active"] and self.error else None}

    def status(self, now: float) -> None:
        """One startup receipt; only bounded summaries and a consistency digest."""
        payload = {"at": now, **self.panel(), "enabled": self.error is None and self.active.enabled,
                   "current": self.current_panel(),
                   "legacy_sha256": digest(self._legacy) if self._legacy is not None else None}
        log.info("kalshi_probability_epoch_status %s", json.dumps(payload, allow_nan=False, separators=(",", ":")))
