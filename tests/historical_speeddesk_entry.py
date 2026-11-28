"""HISTORICAL ENTRY MECHANISM ONLY: explicit prior-policy fake desk factory.

Use this factory only when a regression needs first entries to exercise the
existing journal, transport, reconciliation, cancel, risk or practice mechanism.
It is not evidence that production authorizes entries or that entries profit.
Production-default containment tests must keep using ``make_desk`` directly.

Only the four newly added containment predicates are overridden. Their previous
protected-window behavior is preserved; all existing admission, fee, risk, mode,
feed, accounting, durability and transport checks continue to execute unchanged.
There is no production setting, environment variable or persisted opt-out.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from nightcrawler.speeddesk_live import EPS, Intent, KalshiLiveDesk
from nightcrawler.speeddesk_model import Side


class HistoricalEntryDesk(KalshiLiveDesk):
    def _entry_contracts(self, window: str, side: Side) -> float:
        return math.inf  # previous candidate sizing used clip and visible same-side depth

    def _entry_allowed(self, window: str, side: Side, size: float, unit: float) -> bool:
        # This new policy check did not exist. The original reserve_intent
        # below still enforces protected windows and preserves its refusal reason.
        return True

    def _entry_intent_allowed(self, client_id: str) -> bool:
        intent = self.intents[client_id]
        return (intent.window not in self.book.protected_windows
                or self.book.strictly_balancing_intent(client_id))

    def _entry_cancel_reason(self, intent: Intent) -> str:
        reserved = self.book.intents[intent.client_order_id]
        return ("pair_protected" if intent.window in self.book.protected_windows
                and reserved.reservation_active and reserved.remaining > EPS
                and not self.book.strictly_balancing_intent(intent.client_order_id) else "")


def make_historical_desk(tmp_path: Path, **kwargs: Any) -> Any:
    from test_speeddesk_live import make_desk

    return make_desk(tmp_path, desk_class=HistoricalEntryDesk, **kwargs)
