"""The recorder and the Family A replay can never place, cancel or amend an order (PROTOCOL.md section 2).

Three layers: the source cannot import or name an order/portfolio client, the transport refuses every
non-public path and has no non-GET method, and a full recorder run through the real ``requests``
stack (with only ``Session.request`` faked) issues nothing but allowlisted public GETs without keys.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

import pytest
import requests
from kalshi_recorder_fixtures import (
    NOW,
    Clock,
    FakeKalshi,
    event_row,
    market_row,
    orderbook,
    sample,
    series_row,
)

from nightcrawler import kalshi_public
from nightcrawler.kalshi_public import API, PublicKalshi, RateLimiter, public_path
from nightcrawler.kalshi_recorder import Recorder, RecorderSettings

SOURCE = Path(__file__).resolve().parents[1] / "src" / "nightcrawler"
_REAL_SESSION_REQUEST = requests.Session.request  # captured at import, before conftest blocks the network
MODULES = ("kalshi_public.py", "kalshi_recorder.py", "kalshi_recorder_store.py", "kalshi_recorder_evidence.py", "kalshi_familya.py",
           "kalshi_familya_universe.py")
FORBIDDEN_MODULES = ("speeddesk_kalshi_client", "speeddesk_live", "speeddesk_live_model", "speeddesk_kalshi_ws",
                     "speeddesk_kalshi", "polymarket_us", "broker", "polydesk", "marcodesk", "deskguard", "withdraw",
                     "risk", "botwallet", "engine")
FORBIDDEN_NAMES = ("create_order", "cancel_order", "amend_order", "decrease_order", "batch_create", "batch_cancel",
                   "place_order", "submit_order", "KALSHI-ACCESS", "kalshi_private_key", "kalshi_key_id", "/portfolio",
                   "requests.post", "requests.put", "requests.delete", "requests.patch", "sign_request", "Ed25519")


def test_sources_import_no_order_portfolio_or_signing_client() -> None:
    for name in MODULES:
        source = (SOURCE / name).read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= {alias.name.split(".")[-1] for alias in node.names}
            elif isinstance(node, ast.ImportFrom):
                imported.add((node.module or "").split(".")[-1])
                imported |= {alias.name for alias in node.names}
        assert not imported & set(FORBIDDEN_MODULES), (name, imported & set(FORBIDDEN_MODULES))
        for word in FORBIDDEN_NAMES:
            assert word not in source, (name, word)
        # No HTTP verb other than GET is ever called on anything.
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr not in ("post", "put", "delete", "patch", "request", "send_order"), (name, node.func.attr)


def test_replay_has_no_network_client_at_all() -> None:
    for name in ("kalshi_familya.py", "kalshi_familya_universe.py", "kalshi_recorder_store.py", "kalshi_recorder_evidence.py"):
        source = (SOURCE / name).read_text(encoding="utf-8")
        assert "import requests" not in source and "websockets" not in source and "urllib.request" not in source


def test_importing_the_recorder_and_replay_loads_no_trading_module() -> None:
    code = ("import sys, json; import nightcrawler.kalshi_recorder, nightcrawler.kalshi_familya; "
            "print(json.dumps(sorted(m for m in sys.modules if m.startswith('nightcrawler'))))")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True,
                         cwd=SOURCE.parents[1], env={"PYTHONPATH": str(SOURCE.parent), "PATH": ""})
    loaded = set(json.loads(out.stdout))
    assert loaded <= {"nightcrawler", "nightcrawler.config", "nightcrawler.kalshi_familya",
                      "nightcrawler.kalshi_familya_universe", "nightcrawler.kalshi_public",
                      "nightcrawler.kalshi_recorder", "nightcrawler.kalshi_recorder_store",
                      "nightcrawler.kalshi_recorder_evidence"}, loaded


@pytest.mark.parametrize("path", ["/events", "/series", "/series/KXHIGHNY", "/series/fee_changes",
                                  "/events/fee_changes", "/markets", "/markets/KXBTCD-26OCT1617-T112499.99",
                                  "/markets/orderbooks", "/markets/KXBTC15M-26OCT131400-00/orderbook",
                                  "/markets/trades", "/historical/cutoff", "/historical/markets",
                                  "/historical/trades", "/incentive_programs"])
def test_protocol_allowlist_is_public(path: str) -> None:
    assert public_path(path)


@pytest.mark.parametrize("path", ["/portfolio/orders", "/portfolio/balance", "/portfolio/positions",
                                  "/portfolio/fills", "/portfolio/orders/batched", "/portfolio/orders/abc/amend",
                                  "/portfolio/orders/abc/decrease", "/orders", "/communications/rfqs",
                                  "/communications/quotes", "/api_keys", "/login", "/markets/X/orderbook/../../orders",
                                  "/portfolio/settlements", "/exchange/status", "markets", "/markets/x", ""])
def test_every_account_order_or_unknown_path_is_refused(path: str) -> None:
    assert not public_path(path)


def test_transport_has_only_get_and_refuses_before_any_network_call() -> None:
    assert [name for name in vars(PublicKalshi) if not name.startswith("_")] == ["get"]
    calls: list[Any] = []

    class Session:
        def get(self, *args: Any, **kwargs: Any) -> Any:
            calls.append((args, kwargs))
            raise AssertionError("network reached")

    clock = Clock()
    client = PublicKalshi(RateLimiter(2.0, clock=clock.mono, sleep=clock.sleep), session=Session(), wall=clock.wall,
                          mono=clock.mono)
    with pytest.raises(ValueError, match="public"):
        client.get("x", "/portfolio/orders")
    with pytest.raises(ValueError, match="allowlist"):
        client.get("x", "/markets", {"order_id": "abc"})
    assert calls == []


def test_a_full_recorder_run_issues_only_public_keyless_gets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every lane runs through the real requests stack; only Session.request is replaced by the fake venue."""
    fake = FakeKalshi()
    fake.series = {"KXHIGHNY": series_row()}
    fake.events = [event_row()]
    fake.markets = {"KXHIGHNY-26OCT15-T76": market_row()}
    fake.books = {"KXHIGHNY-26OCT15-T76": orderbook([("0.30", "12.00")], [("0.67", "40.00")])}
    btc = sample("KXBTC15M-metadata.json")["data"]["markets"][0]
    fake.routes["/series/KXBTC15M"] = lambda query: _response({"series": series_row("KXBTC15M", "Crypto")})
    original = fake.route

    def route(path: str, query: dict[str, list[str]]) -> Any:
        if path == "/markets" and query.get("series_ticker") == ["KXBTC15M"]:
            return _response({"markets": [btc], "cursor": ""})
        return original(path, query)

    fake.route = route  # type: ignore[method-assign]
    fake.books[btc["ticker"]] = sample("KXBTC15M-round1.json")["data"]["orderbook_fp"]
    methods: list[str] = []

    def request(self: requests.Session, method: str, url: str, **kwargs: Any) -> Any:
        methods.append(method)
        return fake(method, url, params=kwargs.get("params"), headers=kwargs.get("headers"),
                    allow_redirects=kwargs.get("allow_redirects"))

    monkeypatch.setattr(requests.Session, "request", request)
    clock = Clock(NOW)
    client = PublicKalshi(RateLimiter(2.0, clock=clock.mono, sleep=clock.sleep), wall=clock.wall, mono=clock.mono)
    recorder = Recorder(RecorderSettings(data_dir=tmp_path), client=client, wall=clock.wall)
    stop = threading.Event()
    for _ in range(400):
        if not recorder.step(stop):
            clock.sleep(0.5)
    recorder.close()
    assert methods and set(methods) == {"GET"}
    assert {call["path"] for call in fake.calls} >= {"/markets/orderbooks", "/markets/trades", "/events", "/series",
                                                     "/markets", "/series/fee_changes", "/events/fee_changes"}
    for call in fake.calls:
        assert call["url"].startswith(API) and public_path(call["path"]), call["url"]
        assert call["kwargs"].get("allow_redirects") is False
        assert not any(key.lower().startswith(("kalshi-access", "authorization")) for key in call["headers"])


def test_the_kalshi_public_module_never_mentions_a_secret_variable() -> None:
    source = Path(kalshi_public.__file__).read_text(encoding="utf-8")
    assert "os.environ" not in source and "Secret" not in source


def _response(body: Any) -> Any:
    from kalshi_recorder_fixtures import FakeResponse

    return FakeResponse(200, body)


def test_what_is_actually_sent_carries_no_credentials_even_with_a_netrc_and_a_cookie(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Review F9: intercept the PreparedRequest at the adapter, after requests' netrc/cookie/proxy handling."""
    import io

    from requests.adapters import HTTPAdapter
    from requests.structures import CaseInsensitiveDict

    netrc = tmp_path / "netrc"
    netrc.write_text("machine api.elections.kalshi.com login someone password hunter2\n")
    netrc.chmod(0o600)
    monkeypatch.setenv("NETRC", str(netrc))
    fake = FakeKalshi()
    fake.series = {"KXHIGHNY": series_row()}
    fake.events = [event_row()]
    fake.markets = {"KXHIGHNY-26OCT15-T76": market_row()}
    fake.books = {"KXHIGHNY-26OCT15-T76": orderbook([("0.30", "12.00")], [("0.67", "40.00")])}
    sent: list[requests.PreparedRequest] = []

    def send(self: HTTPAdapter, request: requests.PreparedRequest, **kwargs: Any) -> requests.Response:
        sent.append(request)
        reply = fake(str(request.method), str(request.url), headers=dict(request.headers))
        response = requests.Response()
        response.status_code = reply.status_code
        response.headers = CaseInsensitiveDict({"Set-Cookie": "session=abc; Path=/", **reply.headers})
        response.raw = io.BytesIO(reply._raw)
        response.url, response.request = str(request.url), request
        return response

    monkeypatch.setattr(HTTPAdapter, "send", send)  # nothing can leave the process: the adapter is the fake venue
    monkeypatch.setattr(requests.Session, "request", _REAL_SESSION_REQUEST)  # the real netrc/cookie/proxy handling
    # The probe would catch a regression: a plain session does attach the netrc login.
    plain = requests.Session()
    plain.get(API + "/events")
    assert "Authorization" in sent.pop().headers
    clock = Clock(NOW)
    client = PublicKalshi(RateLimiter(2.0, clock=clock.mono, sleep=clock.sleep), wall=clock.wall, mono=clock.mono)
    client._session.cookies.set("session", "abc", domain="api.elections.kalshi.com", path="/")
    recorder = Recorder(RecorderSettings(data_dir=tmp_path, btc15m=False), client=client, wall=clock.wall)
    for _ in range(150):
        if not recorder.step():
            clock.sleep(0.5)
    recorder.close()
    assert len(sent) > 20 and {request.method for request in sent} == {"GET"}
    for request in sent:
        assert str(request.url).startswith(API + "/")
        names = {name.lower() for name in request.headers}
        assert not names & {"authorization", "cookie", "proxy-authorization"}, request.headers
        assert not any(name.startswith("kalshi-access") for name in names)
        assert request.body is None
