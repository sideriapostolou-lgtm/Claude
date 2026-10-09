"""The 3D town (/office3d, nightcrawler.office3d): static render and purity, the CSP hashes of the inline module and
style, the cast and the pavilions covering every member, the route (auth, headers, methods), the bundled three.js
asset route (whitelist, auth, no traversal, integrity) and the one page's link to it."""

from __future__ import annotations

import base64
import hashlib
import http.client
import json
import re
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fakes import FakeClock

from nightcrawler.config import Settings
from nightcrawler.dashboard import DashboardServer, build_state
from nightcrawler.ledger import Ledger
from nightcrawler.office import PIPELINE
from nightcrawler.office3d import (
    ASSET_FILES,
    CAST3D,
    OFFICE3D_CSP,
    OFFICES3D,
    THREE_SHA256,
    THREE_SOURCE,
    THREE_VERSION,
    asset_bytes,
    render_office3d_html,
)
from nightcrawler.page import MEMBERS, render_page_html
from nightcrawler.teamroom import TeamRoom
from tests.test_page import NOW, TOKEN, live_settings

MEMBER_IDS = [mid for mid, _, _ in MEMBERS]
ASSET = "/office/assets/three.module.min.js"


class Client:
    def __init__(self, server: DashboardServer) -> None:
        self.port = server.bound_port

    def request(self, path: str, method: str = "GET", headers: dict[str, str] | None = None
                ) -> tuple[int, http.client.HTTPMessage, bytes]:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.request(method, path, headers=headers or {})
            res = conn.getresponse()
            return res.status, res.headers, res.read()
        finally:
            conn.close()


@pytest.fixture
def ledger(tmp_path: Path, fake_clock: FakeClock) -> Iterator[Ledger]:
    with Ledger(tmp_path / "nc.db", clock=fake_clock) as led:
        yield led


@pytest.fixture
def serve() -> Iterator[Callable[..., Client]]:
    servers: list[DashboardServer] = []

    def _serve(settings: Settings, ledger: Ledger) -> Client:
        cache: dict[str, Any] = {}
        team = TeamRoom(settings, ledger=ledger, clock=FakeClock(NOW), environ={})
        server = DashboardServer(settings, lambda: build_state(ledger, settings, NOW, cache), host="127.0.0.1",
                                 port=0, team=team)
        server.start()
        servers.append(server)
        return Client(server)

    yield _serve
    for server in servers:
        server.stop()


def _hash(text: str) -> str:
    return "'sha256-" + base64.b64encode(hashlib.sha256(text.encode("utf-8")).digest()).decode("ascii") + "'"


def _module(page: str) -> str:
    return re.search(r'<script type="module">(.*?)</script>', page, re.DOTALL).group(1)


# --------------------------------------------------------------------------- the page


def test_office3d_is_static_and_lists_every_member(settings: Settings) -> None:
    page = render_office3d_html(settings)
    assert page.startswith("<!doctype html>") and '<canvas id="view">' in page and "PAPER" in page
    for mid, name, role in MEMBERS:
        assert f'data-id="{mid}"' in page and f'data-name="{name}"' in page and f'data-role="{role}"' in page
    assert f'data-pipeline="{",".join(PIPELINE)}"' in page
    module = _module(page)
    assert module.lstrip().startswith('import * as THREE from "./office/assets/three.module.min.js";')
    assert "api/page" in module and "http" not in module  # the data and the module come from this server only
    assert "innerHTML" not in page and "eval(" not in page and "insertAdjacentHTML" not in page  # text only, ever
    assert "textContent" in module and "fillText" in module  # words go on screen as text, on canvas as text
    assert "devicePixelRatio" in module and "Math.min(2, window.devicePixelRatio" in module
    assert "visibilitychange" in module and "requestAnimationFrame" in module  # paused while hidden
    assert "shadowMap" not in module  # no shadows: built for phones
    assert "Cannot reach the bot" in module and "no WebGL" in module  # the two honest fallbacks
    assert "A visualisation of the bot's own ledger" in page  # the footer line
    assert 'href="office"' in page and 'href="./"' in page  # the way back
    assert not re.search(r"""(?:src|href)\s*=\s*["']?(?:https?:)?//""", page)
    assert render_office3d_html(settings) == page  # pure


def test_office3d_live_mode_is_marked(make_settings: Callable[..., Settings]) -> None:
    page = render_office3d_html(live_settings(make_settings))
    assert 'class="mode live" id="mode">LIVE</b>' in page and "Night Shift: the town · live" in page


def test_office3d_data_blocks_are_json_that_cannot_break_out(settings: Settings) -> None:
    page = render_office3d_html(settings)
    for block_id, expected in (("cast", CAST3D), ("offices", OFFICES3D)):
        raw = re.search(rf'<script id="{block_id}" type="application/json">(.*?)</script>', page, re.DOTALL).group(1)
        assert "<" not in raw and ">" not in raw and "&" not in raw
        assert json.loads(raw) == expected


def test_office3d_csp_hashes_match_the_inline_module_and_style(settings: Settings) -> None:
    page = render_office3d_html(settings)
    style = re.search(r"<style>(.*?)</style>", page, re.DOTALL).group(1)
    assert _hash(style) in OFFICE3D_CSP and _hash(_module(page)) in OFFICE3D_CSP
    assert OFFICE3D_CSP.startswith("default-src 'none'; script-src 'self' 'sha256-")
    assert "; style-src 'sha256-" in OFFICE3D_CSP and OFFICE3D_CSP.endswith(
        "; connect-src 'self'; img-src 'self' data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
    assert "'unsafe-inline'" not in OFFICE3D_CSP and "'unsafe-eval'" not in OFFICE3D_CSP
    assert page.count("<script") == 3  # the two JSON data blocks and the one module: nothing else runs


# --------------------------------------------------------------------------- the cast and the world


def test_the_cast_plays_every_member_once_and_lives_in_a_real_office() -> None:
    played = [m for c in CAST3D.values() for m in c["members"]]
    assert sorted(played) == sorted(set(played))  # each role has one actor
    assert set(played) == set(MEMBER_IDS)  # nobody on the team is left out, nobody is invented
    for c in CAST3D.values():
        assert c["office"] in OFFICES3D and c["name"] and c["kind"] and c["job"]
    assert {c["office"] for c in CAST3D.values()} == set(OFFICES3D) - {"observatory"}  # one resident per office


def test_every_member_has_exactly_one_status_light() -> None:
    housed = [m for o in OFFICES3D.values() for m in o["members"]]
    assert sorted(housed) == sorted(MEMBER_IDS)
    assert sorted(o["slot"] for o in OFFICES3D.values()) == list(range(len(OFFICES3D))) and len(OFFICES3D) == 7
    for o in OFFICES3D.values():
        assert o["title"] and o["line"] and o["style"]
        for key in ("wall", "roof", "trim"):
            assert re.fullmatch(r"#[0-9a-f]{6}", o[key])
    assert OFFICES3D["observatory"]["members"] == ["coach"]  # the Coach's lab
    assert set(OFFICES3D["vault"]["members"]) == {"risk"} and set(OFFICES3D["dock"]["members"]) == {"broker"}


def test_the_bundled_three_js_is_the_pinned_release() -> None:
    assert ASSET_FILES == {"three.module.min.js": "application/javascript; charset=utf-8"}
    data = asset_bytes("three.module.min.js")
    assert data is not None and hashlib.sha256(data).hexdigest() == THREE_SHA256
    assert data.startswith(b"/**\n * @license\n * Copyright 2010-2023 Three.js Authors\n * SPDX-License-Identifier: MIT")
    assert b'const t="160"' in data[:400] and THREE_VERSION == "0.160.1" and THREE_VERSION in THREE_SOURCE
    assert b"export{" in data[-20000:]  # an ES module, as the inline module imports it
    for bad in ("../office3d.py", "office3d.py", "", "three.module.min.js.map", "/three.module.min.js"):
        assert asset_bytes(bad) is None, bad


# --------------------------------------------------------------------------- the routes


def test_office3d_route_auth_headers_and_methods(serve: Callable[..., Client], ledger: Ledger,
                                                 make_settings: Callable[..., Settings]) -> None:
    client = serve(make_settings(DASHBOARD_TOKEN=TOKEN), ledger)
    status, _, body = client.request("/office3d")
    assert status == 401 and b"Locked" in body
    status, headers, body = client.request(f"/office3d?token={TOKEN}")
    assert status == 200 and headers["Content-Type"].startswith("text/html")
    assert headers["Content-Security-Policy"] == OFFICE3D_CSP and b'<canvas id="view">' in body
    assert headers["X-Frame-Options"] == "DENY" and headers["Cache-Control"] == "no-store"
    cookie = headers["Set-Cookie"].split(";")[0]
    status, headers, _ = client.request("/office3d", headers={"Cookie": cookie})
    assert status == 200 and "Set-Cookie" not in headers
    status, headers, _ = client.request("/office3d", method="POST", headers={"Cookie": cookie})
    assert status == 405 and headers["Allow"] == "GET"
    for bad in ("/office3d.html", "/office3d/", "/office3d/x"):
        assert client.request(bad, headers={"Cookie": cookie})[0] == 404, bad


def test_the_three_js_asset_is_served_behind_the_token_from_a_whitelist(
        serve: Callable[..., Client], ledger: Ledger, make_settings: Callable[..., Settings]) -> None:
    client = serve(make_settings(DASHBOARD_TOKEN=TOKEN), ledger)
    status, _, _ = client.request(ASSET)
    assert status == 401  # the module is private too
    status, headers, _ = client.request(f"/office3d?token={TOKEN}")
    cookie = headers["Set-Cookie"].split(";")[0]
    status, headers, body = client.request(ASSET, headers={"Cookie": cookie})
    assert status == 200 and headers["Content-Type"] == "application/javascript; charset=utf-8"
    assert body == asset_bytes("three.module.min.js") and hashlib.sha256(body).hexdigest() == THREE_SHA256
    assert headers["Cache-Control"] == "private, max-age=86400" and headers["X-Content-Type-Options"] == "nosniff"
    status, _, _ = client.request(f"{ASSET}?token={TOKEN}")
    assert status == 200  # the token works on the asset itself too
    for bad in ("/office/assets/", "/office/assets/nope.js", "/office/assets/..%2Foffice3d.py",
                "/office/assets/../office3d.py", "/office/assets/three.module.min.js.map", "/office/assets/three.module.min.js/",
                "/office/assets/%2e%2e/office3d.py"):
        status, _, _ = client.request(bad, headers={"Cookie": cookie})
        assert status == 404, bad
    status, headers, _ = client.request(ASSET, method="POST", headers={"Cookie": cookie})
    assert status == 405 and headers["Allow"] == "GET"


def test_office3d_without_token_is_open_like_the_page(serve: Callable[..., Client], ledger: Ledger,
                                                      settings: Settings) -> None:
    client = serve(settings, ledger)
    status, headers, body = client.request("/office3d")
    assert status == 200 and b"the town and its cast are drawings" in body
    assert headers["Content-Security-Policy"] == OFFICE3D_CSP
    status, headers, _ = client.request(ASSET)
    assert status == 200 and headers["Content-Type"].startswith("application/javascript")


def test_the_page_and_the_office_link_to_the_town(settings: Settings) -> None:
    page = render_page_html(settings)
    assert '<a class="office" href="office3d" title="The 3D world">3D</a>' in page
    assert page.index('href="office"') < page.index('href="office3d"')  # next to the Office link
    assert 'href="office"' in render_office3d_html(settings)  # and the way back from the town
