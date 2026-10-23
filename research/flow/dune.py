"""Minimal Dune API client for research-only data pulls.

Reads the API key from the ``DUNE_API_KEY`` environment variable; the key is
never written to disk or logged. Supports running ad-hoc SQL (execute → poll →
paginate results) and saving results as JSON lines.

Usage::

    DUNE_API_KEY=... python research/flow/dune.py "select 1 as x" out.jsonl
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import requests

API = "https://api.dune.com/api/v1"


class DuneError(RuntimeError):
    pass


class Dune:
    def __init__(self, api_key: str | None = None, performance: str = "medium") -> None:
        key = api_key or os.environ.get("DUNE_API_KEY")
        if not key:
            raise DuneError("DUNE_API_KEY is not set")
        self._session = requests.Session()
        self._session.headers["X-Dune-Api-Key"] = key
        self.performance = performance

    def __repr__(self) -> str:  # never expose the key
        return f"Dune(performance={self.performance!r})"

    def _request(self, method: str, path: str, **kwargs) -> dict:
        for attempt in range(6):
            resp = self._session.request(method, f"{API}{path}", timeout=60, **kwargs)
            if resp.status_code == 429:
                time.sleep(min(60, 5 * 2 ** attempt))
                continue
            if not resp.ok:
                raise DuneError(f"{method} {path} -> HTTP {resp.status_code}: {resp.text[:500]}")
            return resp.json()
        raise DuneError(f"{method} {path} rate-limited repeatedly")

    def execute_sql(self, sql: str) -> str:
        body = {"sql": sql, "performance": self.performance}
        return self._request("POST", "/sql/execute", json=body)["execution_id"]

    def wait(self, execution_id: str, poll_s: float = 3.0, timeout_s: float = 1800) -> dict:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            status = self._request("GET", f"/execution/{execution_id}/status")
            state = status.get("state")
            if state == "QUERY_STATE_COMPLETED":
                return status
            if state in ("QUERY_STATE_FAILED", "QUERY_STATE_CANCELLED", "QUERY_STATE_EXPIRED"):
                raise DuneError(f"execution {execution_id} {state}: {json.dumps(status)[:800]}")
            time.sleep(poll_s)
        raise DuneError(f"execution {execution_id} timed out")

    def results(self, execution_id: str, page_size: int = 10_000):
        offset = 0
        while True:
            page = self._request(
                "GET", f"/execution/{execution_id}/results", params={"limit": page_size, "offset": offset}
            )
            rows = (page.get("result") or {}).get("rows") or []
            yield from rows
            next_offset = page.get("next_offset")
            if not rows or next_offset is None:
                return
            offset = next_offset

    def run(self, sql: str) -> tuple[dict, list[dict]]:
        execution_id = self.execute_sql(sql)
        status = self.wait(execution_id)
        return status, list(self.results(execution_id))


def main() -> None:
    sql, out = sys.argv[1], Path(sys.argv[2])
    status, rows = Dune().run(sql)
    with out.open("w") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")
    meta = {k: status.get(k) for k in ("state", "execution_cost_credits", "submitted_at", "execution_ended_at")}
    print(json.dumps({"rows": len(rows), **meta}))


if __name__ == "__main__":
    main()
