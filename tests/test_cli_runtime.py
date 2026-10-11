"""CLI runtime fixes: the exits-only safe mode on an invalid configuration (RT-9) and live positions of
another wallet in ``report`` / ``sell-all`` (F3). Offline: FakeHttp + FakeClock via ``test_cli``'s fixtures."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from nightcrawler import engine as engine_mod
from nightcrawler.cli import EXIT_CONFIG, EXIT_OK
from nightcrawler.ledger import Ledger
from nightcrawler.models import Position
from test_cli import _restore_logging, env, nc  # noqa: F401 - fixtures shared with test_cli
from world import GARY

solders_keypair = pytest.importorskip("solders.keypair")

OTHER_WALLET = "OTHERwa11etAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"

#: Every test runs in test_cli's isolated environment (DATA_DIR = tmp_data_dir, fake clock and HTTP).
pytestmark = pytest.mark.usefixtures("env")


@pytest.fixture
def live_wallet(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> str:
    """Live settings with a real (never funded) bot wallet; returns its address."""
    from nightcrawler.base58 import b58encode

    request.getfixturevalue("env")  # after test_cli's env fixture, which clears these variables
    keypair = solders_keypair.Keypair()
    monkeypatch.setenv("TRADING_MODE", "live")
    monkeypatch.setenv("LIVE_CONFIRM", "I_ACCEPT_REAL_MONEY_RISK")
    monkeypatch.setenv("BOT_WALLET_SECRET", b58encode(bytes(keypair)))
    monkeypatch.setenv("DASHBOARD_HOST", "127.0.0.1")
    return str(keypair.pubkey())


def open_live_position(data_dir: Path, wallet: str, position_id: str = "pos_live") -> None:
    with Ledger(data_dir / "nightcrawler.db") as ledger:
        ledger.upsert_position(Position(id=position_id, mint=GARY, symbol="Gary", pool=None, opened_at=1.0,
                                        token_decimals=6, token_amount=1_000, initial_token_amount=1_000,
                                        mode="live"))
        ledger.set_position_wallet(position_id, wallet)


@pytest.fixture
def boot_once(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """``run`` boots, records what the engine looks like, and shuts down at once (no network)."""
    seen: dict[str, Any] = {}
    original = engine_mod.Engine.run_forever

    def capture(self: engine_mod.Engine) -> None:
        seen.update(engine=self, safe_mode=self.safe_mode, settings=self.settings,
                    blocked=self._entries_blocked_why())
        self.stop()
        original(self)  # boot + shutdown receipts, no loop

    monkeypatch.setattr(engine_mod.Engine, "run_forever", capture)
    return seen


# =========================================================================== RT-9: safe mode


def test_a_bad_setting_with_open_live_positions_starts_an_exits_only_safe_mode(tmp_data_dir, live_wallet, monkeypatch,
                                                                               boot_once, capsys) -> None:
    monkeypatch.setenv("STOP_LOSS_PCT", "18")  # a typo: 18 instead of 0.18
    open_live_position(tmp_data_dir, live_wallet)
    assert nc("run", "--no-dashboard") == EXIT_OK
    err = capsys.readouterr().err
    assert "SAFE MODE" in err and "STOP_LOSS_PCT" in err
    assert boot_once["settings"].trading_mode == "live" and boot_once["settings"].stop_loss_pct == 0.18
    assert boot_once["blocked"].startswith("SAFE MODE")
    assert boot_once["safe_mode"]["defaults_used"] == ["STOP_LOSS_PCT"]
    assert any("STOP_LOSS_PCT" in p for p in boot_once["safe_mode"]["problems"])
    with Ledger(tmp_data_dir / "nightcrawler.db") as ledger:
        assert [r.payload["event"] for r in ledger.receipts() if r.kind == "note"][:1] == ["safe_mode"]
        assert ledger.get_kv("engine.safe_mode")["defaults_used"] == ["STOP_LOSS_PCT"]


def test_a_bad_setting_without_open_live_positions_still_refuses(tmp_data_dir, live_wallet, monkeypatch, boot_once,
                                                                 capsys) -> None:
    monkeypatch.setenv("STOP_LOSS_PCT", "18")
    assert nc("run", "--no-dashboard") == EXIT_CONFIG
    assert "FRACTION" in capsys.readouterr().err and boot_once == {}


def test_paper_positions_never_start_a_safe_mode(tmp_data_dir, monkeypatch, boot_once, capsys) -> None:
    monkeypatch.setenv("STOP_LOSS_PCT", "18")
    open_live_position(tmp_data_dir, OTHER_WALLET)  # a live position, but the bot is configured for paper
    assert nc("run", "--no-dashboard") == EXIT_CONFIG
    assert boot_once == {}


def test_safe_mode_never_trades_live_without_the_live_confirmation(tmp_data_dir, live_wallet, monkeypatch, boot_once,
                                                                   capsys) -> None:
    monkeypatch.delenv("LIVE_CONFIRM")
    open_live_position(tmp_data_dir, live_wallet)
    assert nc("run", "--no-dashboard") == EXIT_CONFIG
    err = capsys.readouterr().err
    assert "LIVE_CONFIRM" in err and "1 open LIVE position" in err and "NOT managed" in err
    assert boot_once == {}


def test_safe_mode_locks_the_dashboard_when_its_token_is_missing(tmp_data_dir, live_wallet, monkeypatch, boot_once,
                                                                 capsys) -> None:
    monkeypatch.delenv("DASHBOARD_HOST")  # public bind address and no DASHBOARD_TOKEN: invalid for live
    open_live_position(tmp_data_dir, live_wallet)
    assert nc("run", "--no-dashboard") == EXIT_OK
    settings = boot_once["settings"]
    assert settings.dashboard_host == "0.0.0.0" and settings.dashboard_token  # Railway's healthcheck still works
    token = settings.dashboard_token.reveal()
    assert len(token) >= 32 and token not in capsys.readouterr().err  # ... but nobody can open the dashboard
    assert boot_once["safe_mode"]["defaults_used"] == ["DASHBOARD_TOKEN (random: dashboard locked)"]


def test_safe_mode_never_writes_a_mis_pasted_secret_into_receipts_kv_or_the_dashboard(tmp_data_dir, live_wallet,
                                                                                         monkeypatch, boot_once,
                                                                                         capsys) -> None:
    """ConfigError problems quote the raw value. A key pasted into the wrong variable (the Helius API key into
    USAGE_HELIUS_MONTHLY_CREDITS) must never reach the hash-chained receipts (exported, cannot be edited),
    the ledger kv or the dashboard: only the variable name and a masked value are kept."""
    from nightcrawler.dashboard import build_state

    key = "3f2b9c1e-7d4a-4e8b-9a6f-0c5d2e1b8a47"  # shaped like a Helius API key
    monkeypatch.setenv("USAGE_HELIUS_MONTHLY_CREDITS", key)
    open_live_position(tmp_data_dir, live_wallet)
    assert nc("run", "--no-dashboard") == EXIT_OK
    capsys.readouterr()
    assert boot_once["safe_mode"]["defaults_used"] == ["USAGE_HELIUS_MONTHLY_CREDITS"]
    assert any("USAGE_HELIUS_MONTHLY_CREDITS" in p for p in boot_once["safe_mode"]["problems"])
    assert key not in json.dumps(boot_once["safe_mode"]) and key not in boot_once["blocked"]
    with Ledger(tmp_data_dir / "nightcrawler.db") as ledger:
        assert all(key not in json.dumps(r.payload) for r in ledger.receipts())
        for name in ("engine.safe_mode", "engine.status"):
            assert key not in json.dumps(ledger.get_kv(name))
        state = build_state(ledger, boot_once["settings"], 2e9, {})
        assert state["safe_mode"]["problems"] and key not in json.dumps(state, default=str)


# =========================================================================== F3: another wallet's positions


def test_report_lists_live_positions_of_another_wallet(tmp_data_dir, live_wallet, fake_http, capsys) -> None:
    fake_http.register_fixture("/ultra/v1/holdings/", "jup_ultra_holdings_empty")
    fake_http.register_fixture("/price/v3", "jup_price_v3")
    open_live_position(tmp_data_dir, OTHER_WALLET)
    nc("report")
    out = capsys.readouterr().out
    assert "FOREIGN" in out and "pos_live" in out and OTHER_WALLET in out
    nc("report", "--json")
    data = json.loads(capsys.readouterr().out)
    assert data["foreign_positions"] == [{"id": "pos_live", "mint": GARY, "symbol": "Gary", "wallet": OTHER_WALLET,
                                          "token_amount": 1_000, "opened_at": 1.0}]


def test_sell_all_never_touches_another_wallets_positions(tmp_data_dir, live_wallet, fake_http, capsys) -> None:
    open_live_position(tmp_data_dir, OTHER_WALLET)
    assert nc("sell-all", "--yes") == EXIT_OK
    out = capsys.readouterr().out
    assert "no open positions" in out and "another wallet" in out and OTHER_WALLET in out
    assert fake_http.calls_to("/ultra/v1/order") == []
    with Ledger(tmp_data_dir / "nightcrawler.db") as ledger:
        assert ledger.get_position("pos_live").is_open
