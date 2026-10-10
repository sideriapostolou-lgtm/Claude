"""The office page (/office, "Night Shift: Skyport"): static render, CSP hashes, the cast-to-role mapping, the
route (auth, headers, methods), the bundled concept-art sets (whitelist, auth, no traversal) and the data contract it
draws from (the one page's /api/page fields the script reads)."""

from __future__ import annotations

import base64
import hashlib
import http.client
import re
from collections.abc import Callable, Iterator
from typing import Any

import pytest

from nightcrawler.config import Settings
from nightcrawler.dashboard import DashboardServer, build_state
from nightcrawler.ledger import Ledger
from nightcrawler.office import (
    ART_FILES,
    CAST,
    OFFICE_CSP,
    PIPELINE,
    SHOTS,
    art_bytes,
    render_office_html,
)
from nightcrawler.page import MEMBERS
from nightcrawler.teamroom import TeamRoom
from tests.test_page import (  # noqa: F401 (fixture)
    NOW,
    TOKEN,
    FakeClock,
    ledger,
    live_settings,
)

MEMBER_IDS = [mid for mid, _, _ in MEMBERS]


class Client:
    def __init__(self, server: DashboardServer) -> None:
        self.port = server.bound_port

    def request(
        self, path: str, method: str = "GET", headers: dict[str, str] | None = None
    ) -> tuple[int, http.client.HTTPMessage, bytes]:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.request(method, path, headers=headers or {})
            res = conn.getresponse()
            return res.status, res.headers, res.read()
        finally:
            conn.close()


@pytest.fixture
def serve() -> Iterator[Callable[..., Client]]:
    servers: list[DashboardServer] = []

    def _serve(settings: Settings, ledger: Ledger) -> Client:
        cache: dict[str, Any] = {}
        team = TeamRoom(settings, ledger=ledger, clock=FakeClock(NOW), environ={})
        server = DashboardServer(
            settings,
            lambda: build_state(ledger, settings, NOW, cache),
            host="127.0.0.1",
            port=0,
            team=team,
        )
        server.start()
        servers.append(server)
        return Client(server)

    yield _serve
    for server in servers:
        server.stop()


def _hash(text: str) -> str:
    return (
        "'sha256-"
        + base64.b64encode(hashlib.sha256(text.encode("utf-8")).digest()).decode(
            "ascii"
        )
        + "'"
    )


def test_office_is_static_and_lists_every_member(settings: Settings) -> None:
    page = render_office_html(settings)
    assert (
        page.startswith("<!doctype html>")
        and '<div id="stage">' in page
        and "PAPER" in page
    )
    for mid, name, role in MEMBERS:
        assert (
            f'data-id="{mid}"' in page
            and f'data-name="{name}"' in page
            and f'data-role="{role}"' in page
        )
    assert f'data-pipeline="{",".join(PIPELINE)}"' in page and set(PIPELINE) <= set(
        MEMBER_IDS
    )
    assert (
        "THE SAFE" in page
        and "api/page" in page
        and "http"
        not in page.split("<script>")[1].split("</script>")[0].replace("https", "")
    )
    assert "innerHTML" not in page and "eval(" not in page  # text only, ever
    assert (
        "concept art" in page and "office/art/" in page
    )  # the sets are labelled and loaded from this server
    assert render_office_html(settings) == page  # pure


def test_the_cast_covers_the_team_and_the_sets_exist() -> None:
    played = [m for c in CAST.values() for m in c["members"]]
    assert sorted(played) == sorted(set(played)) and set(played) <= set(
        MEMBER_IDS
    )  # each role has one actor
    assert (
        set(MEMBER_IDS) - set(played) == set()
    )  # nobody on the team is left out of the film
    for c in CAST.values():
        assert c["shot"] in ART_FILES and c["shot"] in SHOTS
    for name in ART_FILES:
        data = art_bytes(name)
        assert (
            data is not None and data[:3] == b"\xff\xd8\xff" and len(data) < 400_000
        )  # a web-sized JPEG
    assert (
        art_bytes("../office.py") is None
        and art_bytes("office.py") is None
        and art_bytes("") is None
    )


def test_office_live_mode_is_marked(make_settings: Callable[..., Settings]) -> None:
    page = render_office_html(live_settings(make_settings))
    assert (
        'class="mode live" id="mode">SOLANA BOT: REAL</b>' in page
        and "Night Shift: Skyport · Solana bot real" in page
    )


def test_office_csp_hashes_match_the_inline_script_and_style(
    settings: Settings,
) -> None:
    page = render_office_html(settings)
    style = re.search(r"<style>(.*?)</style>", page, re.DOTALL).group(1)
    script = re.search(r"<script>(.*?)</script>", page, re.DOTALL).group(1)
    assert _hash(style) in OFFICE_CSP and _hash(script) in OFFICE_CSP
    assert (
        "default-src 'none'" in OFFICE_CSP
        and "connect-src 'self'" in OFFICE_CSP
        and "'unsafe-inline'" not in OFFICE_CSP
    )


def test_office_route_auth_headers_and_methods(
    serve: Callable[..., Client], ledger: Ledger, make_settings: Callable[..., Settings]
) -> None:
    client = serve(make_settings(DASHBOARD_TOKEN=TOKEN), ledger)
    status, _, body = client.request("/office")
    assert status == 401 and b"Locked" in body
    status, headers, body = client.request(f"/office?token={TOKEN}")
    assert status == 200 and headers["Content-Type"].startswith("text/html")
    assert (
        headers["Content-Security-Policy"] == OFFICE_CSP and b'<div id="stage">' in body
    )
    cookie = headers["Set-Cookie"].split(";")[0]
    status, headers, _ = client.request("/office", headers={"Cookie": cookie})
    assert status == 200 and "Set-Cookie" not in headers
    status, headers, _ = client.request(
        "/office", method="POST", headers={"Cookie": cookie}
    )
    assert status == 405 and headers["Allow"] == "GET"
    status, _, _ = client.request("/office.html")
    assert status == 404


def test_office_art_is_served_behind_the_token_from_a_whitelist(
    serve: Callable[..., Client], ledger: Ledger, make_settings: Callable[..., Settings]
) -> None:
    client = serve(make_settings(DASHBOARD_TOKEN=TOKEN), ledger)
    status, _, _ = client.request("/office/art/05_vault_rook.jpg")
    assert status == 401  # the sets are private too
    status, headers, body = client.request(f"/office?token={TOKEN}")
    cookie = headers["Set-Cookie"].split(";")[0]
    status, headers, body = client.request(
        "/office/art/05_vault_rook.jpg", headers={"Cookie": cookie}
    )
    assert (
        status == 200
        and headers["Content-Type"] == "image/jpeg"
        and body == art_bytes("05_vault_rook.jpg")
    )
    assert (
        headers["Cache-Control"] == "private, max-age=86400"
        and headers["X-Content-Type-Options"] == "nosniff"
    )
    for bad in (
        "/office/art/",
        "/office/art/nope.jpg",
        "/office/art/..%2Foffice.py",
        "/office/art/05_vault_rook.png",
    ):
        status, _, _ = client.request(bad, headers={"Cookie": cookie})
        assert status == 404, bad
    status, headers, _ = client.request(
        "/office/art/05_vault_rook.jpg", method="POST", headers={"Cookie": cookie}
    )
    assert status == 405 and headers["Allow"] == "GET"


def test_office_without_token_is_open_like_the_page(
    serve: Callable[..., Client], ledger: Ledger, settings: Settings
) -> None:
    client = serve(settings, ledger)
    status, headers, body = client.request("/office")
    assert (
        status == 200
        and b"THE SAFE" in body
        and headers["Content-Security-Policy"] == OFFICE_CSP
    )


def test_the_page_links_to_the_office(settings: Settings) -> None:
    from nightcrawler.page import render_page_html

    assert 'href="office"' in render_page_html(settings)
