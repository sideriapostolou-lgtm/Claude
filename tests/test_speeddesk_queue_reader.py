"""Queue GET transport uses throwaway keys and fake HTTP, never account credentials."""
from __future__ import annotations

import base64
import io
import json
from types import SimpleNamespace
from typing import Any

import pytest
import requests
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from test_speeddesk_kalshi_client import Transport, client

from nightcrawler.speeddesk_kalshi_client import (
    API_PATH,
    BASE_URL,
    KalshiClientError,
    OwnQueueReader,
)


class Reply:
    def __init__(self, data: Any = None, *, body: bytes | None = None, status: int = 200,
                 headers: dict[str, str] | None = None) -> None:
        self.body = json.dumps(data if data is not None else {'queue_position_fp': '2.50'}).encode() if body is None else body
        self.status_code, self.headers = status, headers or {}
        self.closed = False

    def iter_content(self, chunk_size: int):
        for index in range(0, len(self.body), chunk_size):
            yield self.body[index:index + chunk_size]

    def close(self):
        self.closed = True


class Session:
    def __init__(self, reply: Reply | Exception) -> None:
        self.reply, self.calls = reply, []
        self.cookies = requests.cookies.RequestsCookieJar()
        self.closed = False

    def get(self, url: str, **kwargs: Any):
        self.calls.append((url, kwargs))
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply

    def close(self):
        self.closed = True


def reader(reply: Reply | Exception, *, claim=lambda: True, mono=lambda: 0.0):
    c = client(Ed25519PrivateKey.generate(), Transport())
    s = Session(reply)
    return OwnQueueReader(c.headers, claim, session=s, monotonic=mono), s, c


@pytest.mark.parametrize('value', ['0.00', '2.50', '123456.78'])
def test_fixed_point_counts_and_single_signed_get(value):
    reply = Reply({'queue_position_fp': value})
    r, session, c = reader(reply)
    try:
        assert r.read('owned-order') == value
        [(url, kwargs)] = session.calls
        assert url == BASE_URL + API_PATH + '/portfolio/orders/owned-order/queue_position'
        assert kwargs['allow_redirects'] is False and kwargs['stream'] is True
        assert kwargs['timeout'] == (1.0, 1.0)
        assert 'json' not in kwargs and 'params' not in kwargs
        headers = kwargs['headers']
        c._signer.public_key().verify(base64.b64decode(headers['KALSHI-ACCESS-SIGNATURE']),
            (headers['KALSHI-ACCESS-TIMESTAMP'] + 'GET' + API_PATH + '/portfolio/orders/owned-order/queue_position').encode())
        assert reply.closed
    finally:
        r.close(); c.close()


@pytest.mark.parametrize('value', [None, 0, 2.5, True, '-1.00', '1', '1.0', '1.000', '1e2', 'NaN', 'inf', '9' * 40 + '.00'])
def test_malformed_counts_are_unknown_not_zero(value):
    reply = Reply({'queue_position_fp': value})
    r, session, c = reader(reply)
    try:
        with pytest.raises(KalshiClientError, match='observer_invalid_response'):
            r.read('owned')
        assert reply.closed and len(session.calls) == 1
    finally:
        r.close(); c.close()


@pytest.mark.parametrize('reply,reason', [
    (Reply(body=b'[]'), 'observer_invalid_response'), (Reply(body=b'{'), 'observer_invalid_response'),
    (Reply({}, headers={'Content-Length': '8193'}), 'observer_response_size'),
    (Reply(body=b' ' * 8193), 'observer_response_size'), (Reply(status=404), 'observer_http_error'),
    (Reply(status=429), 'observer_http_error'), (requests.Timeout('DO_NOT_LOG'), 'observer_transport_timeout'),
])
def test_http_errors_bounds_and_safe_messages(reply, reason):
    r, session, c = reader(reply)
    try:
        with pytest.raises(KalshiClientError, match=reason) as error:
            r.read('owned')
        assert 'DO_NOT_LOG' not in str(error.value)
        assert c._blocked_until == 0 and not c._rate_failures
        assert len(session.calls) == 1
        if isinstance(reply, Reply):
            assert reply.closed
    finally:
        r.close(); c.close()


def test_body_elapsed_guard_closes_response():
    moments = iter([0, .5, 3])
    reply = Reply()
    r, _, c = reader(reply, mono=lambda: next(moments))
    try:
        with pytest.raises(KalshiClientError, match='observer_body_deadline'):
            r.read('owned')
        assert reply.closed
    finally:
        r.close(); c.close()


@pytest.mark.parametrize('order_id', ['', '../owner', 'a?x=y', 'x/y', 'x' * 129])
def test_path_refuses_arbitrary_ids_without_http(order_id):
    r, session, c = reader(Reply())
    try:
        with pytest.raises(KalshiClientError):
            r.read(order_id)
        assert not session.calls
    finally:
        r.close(); c.close()


def test_nonblocking_shared_quota_headroom_and_no_execution_transport_lock():
    key = Ed25519PrivateKey.generate()
    c = client(key, Transport(), reads_per_s=3)
    session = Session(Reply(status=429))
    r = OwnQueueReader(c.headers, c._try_queue_read_slot, session=session)
    try:
        with c._budget_lock:
            assert not c._try_queue_read_slot()
        c._locks[False].acquire(); c._locks[True].acquire()
        try:
            with pytest.raises(KalshiClientError) as error:
                r.read('owned')
            assert error.value.status == 429  # GET did not wait for either execution transport lock
        finally:
            c._locks[False].release(); c._locks[True].release()
        assert c._try_queue_read_slot()  # two local reads claimed; one slot still reserved for account work
        assert not c._try_queue_read_slot()
        assert c._blocked_until == 0
    finally:
        r.close(); c.close()


def test_signed_headers_keep_proxy_ca_but_never_netrc_or_cookies(monkeypatch):
    c = client(Ed25519PrivateKey.generate(), Transport())
    class InspectSession(requests.Session):
        def get(self, url, **kwargs):
            # Exercise requests' real preparation/environment merge without invoking the suite's blocked
            # network entry point. send below is a fake, so no request can reach an adapter or socket.
            prepared = self.prepare_request(requests.Request('GET', url, headers=kwargs['headers'], auth=kwargs['auth']))
            settings = self.merge_environment_settings(url, {}, kwargs['stream'], True, None)
            return self.send(prepared, **settings)

        def send(self, request, **kwargs):
            self.prepared, self.settings = request, kwargs
            response = requests.Response()
            response.status_code = 200
            response.raw = io.BytesIO(b'{"queue_position_fp":"0.00"}')
            response.headers = {}
            response.request = request
            return response
    session = InspectSession()
    session.cookies.set('owner_cookie', 'DO_NOT_SEND')
    def forbidden_netrc(*_args):
        raise AssertionError('must not read netrc')
    monkeypatch.setattr(requests.sessions, 'get_netrc_auth', forbidden_netrc)
    monkeypatch.setattr(requests.sessions, 'get_environ_proxies', lambda *_args, **_kwargs: {'https': 'http://fake-proxy.invalid'})
    monkeypatch.setattr(requests.sessions, 'os', SimpleNamespace(environ={'REQUESTS_CA_BUNDLE': '/fake/inherited-ca.pem'}))
    r = OwnQueueReader(c.headers, lambda: True, session=session)
    try:
        assert r.read('owned') == '0.00'
        assert session.trust_env is True
        assert session.settings['proxies']['https'] == 'http://fake-proxy.invalid'
        assert session.settings['verify'] == '/fake/inherited-ca.pem'
        assert 'Authorization' not in session.prepared.headers and 'Cookie' not in session.prepared.headers
        assert session.prepared.headers['KALSHI-ACCESS-KEY'] == 'throwaway-test-id'
        assert not session.cookies
    finally:
        r.close(); c.close()
