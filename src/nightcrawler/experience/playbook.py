"""The playbook: every rule is a tested hypothesis (docs/EXPERIENCE.md §7.1, §7.2). Pure, read-only.

The static registry ``experience/playbook.json`` is GENERATED from the grounded rules (G01-G62) by
``scripts/gen_playbook.py`` (T7): one entry per row with at least ``id`` and its initial ``status``. Status changes
live outside ``src/`` edits - forward tests arrive as receipted ``filter_register`` / ``filter_verdict`` outbox rows
(first row per ``filter_id``) - so a status change never forces a redeploy. Nothing here can change trading: a
``validated`` rule enters the bot only through a human-reviewed PR (§7.5), and the counts are display only.

* :func:`load_entries` - the registry (``[]`` when the file is missing or unreadable; never raises).
* :func:`fold_statuses` - entry statuses with the receipted forward-test events applied in receipt order.
* :func:`counts` - what the page shows ("Rules tested and kept: k (at most 1 in 10 expected to be a false keep)").
* :func:`elond_alpha` - Track F's family-wide e-LOND level for registration j (§7.2).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from nightcrawler.experience.constants import LESSON_Q
from nightcrawler.experience.stats import first_per_key

__all__ = ["STATUSES", "IN_BOT", "PLAYBOOK_PATH", "load_entries", "fold_statuses", "counts", "elond_alpha"]

log = logging.getLogger("nightcrawler.experience.playbook")

STATUSES = ("in_bot_contradicted", "in_bot_unsupported", "fix_engineering", "candidate", "queued", "testing",
            "validated", "rejected", "blocked_data", "parked")
IN_BOT = ("in_bot_contradicted", "in_bot_unsupported")
PLAYBOOK_PATH = Path(__file__).with_name("playbook.json")
#: Track F's family-wide false-discovery level (§7.2), the same q as the lesson e-BH.
TRACK_F_Q = LESSON_Q
_VERDICTS = {"kept": "validated", "dropped": "rejected"}


def load_entries(path: Path = PLAYBOOK_PATH) -> list[dict[str, Any]]:
    """The registry's entries (``{"entries": [...]}`` or a bare list); an entry needs a string ``id``, and an unknown
    status reads as ``candidate`` (untested). Missing or broken file: ``[]``."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        if path.exists():
            log.warning("playbook_unreadable error=%s", type(exc).__name__)
        return []
    items = data.get("entries") if isinstance(data, Mapping) else data
    out = []
    for item in items if isinstance(items, list) else []:
        if isinstance(item, Mapping) and isinstance(item.get("id"), str) and item["id"]:
            status = item.get("status")
            out.append({**item, "status": status if status in STATUSES else "candidate"})
    return out


def fold_statuses(entries: Sequence[Mapping[str, Any]], events: Iterable[Mapping[str, Any]] = ()) -> dict[str, str]:
    """``{id: status}``: the registry's statuses, then receipted ``filter_register`` (-> ``testing``, unless the rule
    is in the bot already, where it stays) and ``filter_verdict`` (``kept`` -> ``validated``, ``dropped`` ->
    ``rejected``) rows naming a known rule in their ``rule`` field."""
    statuses = {str(e["id"]): str(e["status"]) for e in entries}
    for row in first_per_key(events, ("filter_register", "filter_verdict")):
        payload = row.get("payload") or {}
        rule = payload.get("rule")
        if rule not in statuses:
            continue
        if row["event"] == "filter_register" and statuses[rule] not in IN_BOT + ("validated", "rejected"):
            statuses[rule] = "testing"
        elif row["event"] == "filter_verdict" and payload.get("verdict") in _VERDICTS:
            statuses[rule] = _VERDICTS[payload["verdict"]]
    return statuses


def counts(statuses: Mapping[str, str]) -> dict[str, Any]:
    """The page's playbook counts (§9)."""
    values = list(statuses.values())
    return {"validated": values.count("validated"), "rejected": values.count("rejected"),
            "in_bot_contradicted": values.count("in_bot_contradicted"),
            "in_bot_unsupported": values.count("in_bot_unsupported"),
            "testing": values.count("testing") + values.count("queued"), "false_keep_bound": "1 in 10"}


def elond_alpha(j: int, adoptions_before: int, q: float = TRACK_F_Q) -> float:
    """e-LOND level of the j-th (1-based) Track F registration: ``q * gamma_j * (R_j + 1)``, ``gamma_j =
    1 / (j (j + 1))``, ``R_j`` the adoptions receipted before it. Adopted when its forward e-value >= 1 / alpha_j."""
    if j < 1 or adoptions_before < 0:
        raise ValueError("registrations are numbered from 1")
    return q / (j * (j + 1)) * (adoptions_before + 1)
