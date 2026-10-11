"""Test doubles shared by every test module (import as ``from fakes import ...``).

* :class:`FakeHttp` - a fake *transport* (``requests.Session``-compatible
  ``request()``) to plug into the REAL :class:`nightcrawler.http.HttpClient`:
  ``HttpClient(session=fake, clock=FakeClock(), rate_limits={}, default_rate=None)``
  (the ``http_client`` fixture in conftest does exactly that). Routes map URL
  patterns to fixture JSON, callables or status codes; every request is recorded.
* :data:`FakeTransport` - alias of :class:`FakeHttp`.
* :class:`FakeClock` - re-exported from ``nightcrawler.clock``.
* :func:`load_fixture` - read ``tests/fixtures/<name>.json``.

Pattern matching: a plain string matches when it is a SUBSTRING of the full
URL (including the encoded query string); prefix ``re:`` for a regex
(``re.search``). The most recently registered matching route with remaining
``times`` wins, so register the steady-state response first and one-shot
failures (``times=1``) after it.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode

from nightcrawler.clock import FakeClock

__all__ = [
    "FIXTURES_DIR",
    "load_fixture",
    "FakeRequest",
    "FakeResponse",
    "FakeHttp",
    "FakeTransport",
    "FakeClock",
    "UnregisteredURL",
]

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> Any:
    """Parsed JSON of ``tests/fixtures/<name>`` (``.json`` optional)."""
    path = FIXTURES_DIR / (name if name.endswith(".json") else f"{name}.json")
    return json.loads(path.read_text(encoding="utf-8"))


class UnregisteredURL(AssertionError):
    """A request hit FakeHttp without a matching route (tests must be explicit)."""


@dataclass
class FakeRequest:
    method: str
    url: str
    params: dict[str, Any] | None = None
    json: Any = None
    headers: dict[str, str] = field(default_factory=dict)
    timeout: Any = None

    @property
    def full_url(self) -> str:
        if not self.params:
            return self.url
        sep = "&" if "?" in self.url else "?"
        return f"{self.url}{sep}{urlencode(self.params, doseq=True)}"


class FakeResponse:
    """Minimal ``requests.Response`` stand-in."""

    def __init__(self, status_code: int = 200, body: Any = None, headers: dict[str, str] | None = None,
                 url: str = "") -> None:
        self.status_code = status_code
        self.headers = dict(headers or {})
        self.url = url
        if body is None:
            self.content = b""
        elif isinstance(body, bytes):
            self.content = body
        elif isinstance(body, str):
            self.content = body.encode("utf-8")
        else:
            self.content = json.dumps(body).encode("utf-8")
            self.headers.setdefault("Content-Type", "application/json")

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")

    @property
    def ok(self) -> bool:
        return self.status_code < 400

    def json(self) -> Any:
        return json.loads(self.content.decode("utf-8"))


@dataclass
class _Route:
    pattern: str
    response: Any
    status: int
    method: str | None
    headers: dict[str, str]
    times: int | None

    def matches(self, method: str, url: str) -> bool:
        if self.method and self.method.upper() != method.upper():
            return False
        if self.times is not None and self.times <= 0:
            return False
        if self.pattern.startswith("re:"):
            return re.search(self.pattern[3:], url) is not None
        return self.pattern in url


class FakeHttp:
    """Session-compatible fake transport. See module docstring."""

    def __init__(self) -> None:
        self.routes: list[_Route] = []
        self.calls: list[FakeRequest] = []

    def register(self, pattern: str, response: Any = None, status: int = 200, *, method: str | None = None,
                 headers: dict[str, str] | None = None, times: int | None = None) -> "FakeHttp":
        """Add a route. ``response`` may be:

        * JSON-able data (dict/list/number) -> JSON body; ``str``/``bytes`` -> raw body;
          ``None`` -> empty body;
        * a callable ``f(request: FakeRequest)`` returning any of the above, a
          :class:`FakeResponse`, or raising (e.g. ``requests.ConnectionError``);
        * an ``Exception`` instance -> raised when the route is hit.

        ``times``: serve this route at most N times (None = unlimited).
        Returns ``self`` for chaining.
        """
        self.routes.append(_Route(pattern, response, status, method, dict(headers or {}), times))
        return self

    def register_fixture(self, pattern: str, fixture_name: str, status: int = 200, **kw: Any) -> "FakeHttp":
        """Shortcut: ``register(pattern, load_fixture(fixture_name), status, **kw)``."""
        return self.register(pattern, load_fixture(fixture_name), status, **kw)

    # requests.Session-compatible entry point used by HttpClient
    def request(self, method: str, url: str, params: Any = None, json: Any = None, headers: Any = None,
                timeout: Any = None, **_: Any) -> FakeResponse:
        req = FakeRequest(method.upper(), url, dict(params) if params else None, json, dict(headers or {}), timeout)
        self.calls.append(req)
        full = req.full_url
        for route in reversed(self.routes):
            if route.matches(req.method, full):
                if route.times is not None:
                    route.times -= 1
                return self._respond(route, req)
        raise UnregisteredURL(f"FakeHttp: no route for {req.method} {full}")

    def _respond(self, route: _Route, req: FakeRequest) -> FakeResponse:
        body = route.response
        if isinstance(body, BaseException):
            raise body
        if callable(body):
            body = body(req)
        if isinstance(body, FakeResponse):
            if not body.url:
                body.url = req.full_url
            return body
        return FakeResponse(route.status, body, route.headers, req.full_url)

    # assertions helpers
    def calls_to(self, pattern: str) -> list[FakeRequest]:
        """Recorded requests whose full URL contains ``pattern`` (``re:`` prefix for regex)."""
        if pattern.startswith("re:"):
            rx = re.compile(pattern[3:])
            return [c for c in self.calls if rx.search(c.full_url)]
        return [c for c in self.calls if pattern in c.full_url]

    def reset_calls(self) -> None:
        self.calls.clear()


FakeTransport = FakeHttp

# Convenience type for callables used as route responses.
Responder = Callable[[FakeRequest], Any]
