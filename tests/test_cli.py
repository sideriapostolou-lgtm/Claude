"""CLI tests: every subcommand's happy path offline (FakeHttp + FakeClock) plus friendly errors."""

from __future__ import annotations

import json
import logging
import os
import signal
import socket
import sqlite3
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pytest

from fakes import FakeClock, FakeHttp
from nightcrawler import cli
from nightcrawler import engine as engine_mod
from nightcrawler.cli import EXIT_CONFIG, EXIT_ERROR, EXIT_OK, EXIT_USAGE, EXIT_VERIFY_FAILED, main
from nightcrawler.config import load_settings
from nightcrawler.learn import job as learn_job
from nightcrawler.ledger import Ledger
from world import GARY, World, make_world

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "data" / "samples"
REAL_BUILD_APP = engine_mod.build_app


@pytest.fixture(autouse=True)
def _restore_logging() -> Any:
    """The CLI installs a root handler on the (captured) stderr; undo it after each test."""
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    yield
    root.handlers[:] = handlers
    root.setLevel(level)


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch, tmp_data_dir: Path, fake_clock: FakeClock, http_client: Any) -> Path:
    """Isolated settings (DATA_DIR = tmp) and the CLI's clock/HTTP wired to the fakes."""
    for name in ("TRADING_MODE", "LIVE_CONFIRM", "BOT_WALLET_SECRET", "ANTHROPIC_API_KEY", "JUDGE_MODE",
                 "KILL_SWITCH", "DASHBOARD_TOKEN", "PORT", "RESET_HALT_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DATA_DIR", str(tmp_data_dir))
    monkeypatch.setattr(cli, "_make_clock", lambda: fake_clock)
    monkeypatch.setattr(cli, "_http", lambda settings, clock: http_client)

    def build_app(settings: Any, clock: Any = None, **kw: Any) -> Any:
        kw.pop("http", None)
        return REAL_BUILD_APP(settings, fake_clock, http=http_client, **kw)

    monkeypatch.setattr(engine_mod, "build_app", build_app)
    return tmp_data_dir


@pytest.fixture
def world(fake_http: FakeHttp, fake_clock: FakeClock) -> World:
    return make_world(fake_http, fake_clock)


def nc(*args: str) -> int:
    return main(["--env-file", "/nonexistent/.env", *args])


def trade_once(env: Path, fake_clock: FakeClock) -> None:
    """One engine tick in the fake world: discovers, rug-checks and paper-buys GARY."""
    app = engine_mod.build_app(load_settings(dotenv_path=None))
    try:
        app.engine.tick(fake_clock.now())
        assert len(app.ledger.open_positions()) == 1
    finally:
        app.close()


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def get(url: str) -> tuple[int, str]:
    with urllib.request.urlopen(url, timeout=5) as resp:  # noqa: S310 - local test server
        return resp.status, resp.read().decode()


# =========================================================================== config / scan


def test_config_table_hides_secrets(env, monkeypatch, capsys) -> None:
    monkeypatch.setenv("JUPITER_API_KEY", "jup-secret-value-123")
    assert nc("config") == EXIT_OK
    out = capsys.readouterr().out
    assert "TRADING_MODE" in out and "JUPITER_API_KEY_SET" in out and "jup-secret-value-123" not in out


def test_bad_config_exits_3_with_a_hint(env, monkeypatch, capsys) -> None:
    monkeypatch.setenv("STOP_LOSS_PCT", "18")
    assert nc("scan") == EXIT_CONFIG
    assert "FRACTION" in capsys.readouterr().err


def test_scan_prints_pass_and_fail_with_reasons(env, world, capsys) -> None:
    assert nc("scan") == EXIT_OK
    out = capsys.readouterr().out
    assert "2 checked: 1 PASS, 1 FAIL" in out
    lines = {line.split()[1]: line for line in out.splitlines() if line.startswith(("PASS", "FAIL"))}
    assert lines["Gary"].startswith("PASS") and lines["RISKY"].startswith("FAIL")
    assert "[rugcheck_danger]" in lines["RISKY"]
    assert world.http.calls_to("/ultra/v1/order") == []  # scan never trades


def test_scan_json_and_limit(env, world, capsys) -> None:
    assert nc("scan", "--json", "--limit", "1") == EXIT_OK
    data = json.loads(capsys.readouterr().out)
    assert len(data["checked"]) == 1 and data["not_checked"] == 1
    assert data["checked"][0]["safety"]["mint"] in {GARY, data["checked"][0]["candidate"]["mint"]}


def test_scan_include_young_checks_nursery_tokens(env, world, fake_clock, capsys) -> None:
    world.trending[0]["firstPool"]["createdAt"] = cli_iso(fake_clock.now() - 30 * 60)  # GARY is 30 min old
    assert nc("scan") == EXIT_OK
    assert "1 too young" in capsys.readouterr().out
    assert nc("scan", "--include-young") == EXIT_OK
    out = capsys.readouterr().out
    assert any(line.startswith("PASS*") and "Gary" in line for line in out.splitlines())
    assert "YOUNG" in out


def cli_iso(ts: float) -> str:
    from nightcrawler.clock import iso_utc

    return iso_utc(ts) or ""


# =========================================================================== backtest / collect


def test_backtest_one_sample_writes_json(env, tmp_path, capsys) -> None:
    out_file = tmp_path / "bt.json"
    assert nc("backtest", str(SAMPLES / "higgs_1m.json"), "--json", str(out_file)) == EXIT_OK
    out = capsys.readouterr().out
    assert "TOTAL" in out and "Not modelled" in out
    data = json.loads(out_file.read_text())
    assert data["aggregate"]["series"] == 1 and data["results"][0]["coin"]


def test_backtest_folder_with_a_trading_window(env, capsys) -> None:
    assert nc("backtest", str(SAMPLES), "--from", "2026-10-04T22:00", "--until", "2026-10-05T06:00") == EXIT_OK
    out = capsys.readouterr().out
    assert out.count("\n") >= 4 and "TOTAL" in out


def test_backtest_mirrors_the_live_watch_window_unless_any_age(env, tmp_path, capsys) -> None:
    window = ("--from", "2026-10-04T22:00", "--until", "2026-10-05T06:00")
    out_file = tmp_path / "bt.json"
    assert nc("backtest", str(SAMPLES / "higgs_1m.json"), *window, "--json", str(out_file)) == EXIT_OK
    assert json.loads(out_file.read_text())["aggregate"]["trades"] == 0  # HIGGS was 9.5 h old that night
    assert nc("backtest", str(SAMPLES / "higgs_1m.json"), *window, "--any-age", "--json", str(out_file)) == EXIT_OK
    assert json.loads(out_file.read_text())["aggregate"]["trades"] > 0


def test_backtest_sweep_reports_out_of_sample(env, capsys) -> None:
    assert nc("backtest", str(SAMPLES), "--sweep", "--grid", '{"dip_pct": [0.5, 0.6]}') == EXIT_OK
    out = capsys.readouterr().out
    assert "TEST ret%" in out and "best on TRAIN" in out


@pytest.mark.parametrize("args, code, text", [
    (["backtest", "/nope/missing.json"], EXIT_ERROR, "no such file"),
    (["backtest", str(SAMPLES), "--sweep", "--grid", "{bad"], EXIT_USAGE, "not valid JSON"),
    (["backtest", str(SAMPLES), "--from", "yesterday"], EXIT_USAGE, "cannot read time"),
    (["backtest", str(SAMPLES / "higgs_1m.json"), "--sweep"], EXIT_USAGE, "at least 2 series"),
])
def test_backtest_friendly_errors(env, capsys, args, code, text) -> None:
    assert nc(*args) == code
    assert text in capsys.readouterr().err


def test_collect_builds_the_census(env, fake_http, tmp_path, capsys) -> None:
    fake_http.register_fixture("/new_pools", "gt_new_pools")
    fake_http.register_fixture("/ohlcv/minute", "gt_ohlcv_minute")
    out_dir = tmp_path / "ds"
    assert nc("collect", "--pools", "2", "--hours", "1", "--min-age-h", "0", "--out", str(out_dir)) == EXIT_OK
    out = capsys.readouterr().out
    assert "census:" in out and (out_dir / "census.jsonl").is_file()
    assert len(list(out_dir.glob("*.json"))) == 2


def test_collect_first_run_explains_the_census(env, fake_http, tmp_path, capsys) -> None:
    fake_http.register_fixture("/new_pools", "gt_new_pools")
    assert nc("collect", "--out", str(tmp_path / "ds")) == EXIT_OK
    assert "first runs only build the census" in capsys.readouterr().out


# =========================================================================== report / receipts


def test_report_and_receipts_after_a_paper_trade(env, world, fake_clock, tmp_path, capsys) -> None:
    trade_once(env, fake_clock)
    assert nc("report") == EXIT_OK
    out = capsys.readouterr().out
    assert "Result: OK" in out and "PAPER" in out

    assert nc("report", "--json") == EXIT_OK
    assert json.loads(capsys.readouterr().out)["ok"] is True

    assert nc("receipts", "head") == EXIT_OK
    head = capsys.readouterr().out
    seq = int(head.split()[1])
    assert seq >= 4 and len(head.split()[3]) == 64

    assert nc("receipts", "verify") == EXIT_OK
    assert capsys.readouterr().out.startswith("OK")

    export = tmp_path / "receipts.jsonl"
    assert nc("receipts", "export", str(export)) == EXIT_OK
    lines = export.read_text().splitlines()
    assert len(lines) == seq and json.loads(lines[0])["seq"] == 1

    with sqlite3.connect(env / "nightcrawler.db") as conn:  # tamper with history
        conn.execute("UPDATE receipts SET payload = replace(payload, 'enter', 'xxxxx') WHERE kind = 'decision'")
    assert nc("receipts", "verify") == EXIT_VERIFY_FAILED
    assert "BROKEN" in capsys.readouterr().out
    assert nc("report") == EXIT_VERIFY_FAILED


@pytest.mark.parametrize("args", [["report"], ["receipts", "verify"], ["reset-halt", "--yes"]])
def test_commands_needing_a_ledger_explain_when_there_is_none(env, capsys, args) -> None:
    assert nc(*args) == EXIT_ERROR
    assert "no ledger yet" in capsys.readouterr().err


# =========================================================================== wallet


def test_wallet_new_prints_the_secret_exactly_once(env, capsys, caplog) -> None:
    pytest.importorskip("solders")
    caplog.set_level(logging.DEBUG)
    assert nc("wallet", "new") == EXIT_OK
    out = capsys.readouterr().out
    secret = next(line.split()[-1] for line in out.splitlines() if line.startswith("secret"))
    address = next(line.split()[-1] for line in out.splitlines() if line.startswith("address"))
    assert out.count(secret) == 1 and len(address) >= 32
    assert "SHOWN ONCE" in out and "Import Private Key" in out
    assert secret not in caplog.text


def test_wallet_show_needs_a_secret(env, capsys) -> None:
    assert nc("wallet", "show") == EXIT_ERROR
    assert "BOT_WALLET_SECRET is not set" in capsys.readouterr().err


def test_wallet_show_prints_address_and_balances_never_the_secret(env, monkeypatch, fake_http, capsys) -> None:
    keypair = pytest.importorskip("solders.keypair").Keypair()
    from nightcrawler.base58 import b58encode

    secret = b58encode(bytes(keypair))
    monkeypatch.setenv("BOT_WALLET_SECRET", secret)
    fake_http.register_fixture("/ultra/v1/holdings/", "jup_ultra_holdings_synthetic")
    fake_http.register_fixture("/price/v3", "jup_price_v3")
    assert nc("wallet", "show") == EXIT_OK
    out = capsys.readouterr().out
    assert str(keypair.pubkey()) in out and "SOL:" in out and secret not in out


# =========================================================================== sell-all / reset-halt


def test_sell_all_needs_confirmation(env, capsys) -> None:
    assert nc("sell-all") == EXIT_USAGE  # stdin is not a terminal under pytest
    assert "--yes" in capsys.readouterr().err


def test_sell_all_exits_every_position(env, world, fake_clock, capsys) -> None:
    trade_once(env, fake_clock)
    fake_clock.advance(120)  # the bot is not running any more (stale heartbeat)
    assert nc("sell-all", "--yes") == EXIT_OK
    out = capsys.readouterr().out
    assert "sold Gary" in out and "KILL_SWITCH=stop" in out
    with Ledger(env / "nightcrawler.db") as ledger:
        assert ledger.open_positions() == []
        assert ledger.positions(status="closed")[0].exit_reason == "manual"
    assert nc("sell-all", "--yes") == EXIT_OK
    assert "no open positions" in capsys.readouterr().out


def test_sell_all_beside_a_running_bot_hands_the_job_to_the_bot(env, world, fake_clock, capsys) -> None:
    """Two processes trading one ledger race (a stale position copy can be written back), so with a
    fresh heartbeat the CLI only asks the running bot to sell, through the KILL file."""
    trade_once(env, fake_clock)  # the bot's heartbeat is fresh
    assert nc("sell-all", "--yes") == EXIT_OK
    out = capsys.readouterr().out
    assert "running" in out and "KILL" in out
    assert (env / "KILL").read_text().strip() == "sell_all"
    with Ledger(env / "nightcrawler.db") as ledger:
        assert len(ledger.open_positions()) == 1  # the CLI itself sold nothing


def test_reset_halt(env, capsys) -> None:
    with Ledger(env / "nightcrawler.db") as ledger:
        ledger.set_kv("risk.halted", {"halted": True, "reason": "drawdown 52%", "ts": 1.0})
    assert nc("reset-halt", "--yes") == EXIT_OK
    assert "halt cleared" in capsys.readouterr().out
    with Ledger(env / "nightcrawler.db") as ledger:
        assert ledger.get_kv("risk.halted")["halted"] is False
        assert ledger.receipts()[-1].kind == "reset"
    assert nc("reset-halt", "--yes") == EXIT_OK
    assert "not halted" in capsys.readouterr().out


# =========================================================================== run / dashboard


def test_run_starts_dashboard_and_engine_then_stops(env, world, monkeypatch, capsys) -> None:
    port = free_port()
    monkeypatch.setenv("PORT", str(port))
    seen: dict[str, Any] = {}
    original = engine_mod.Engine.run_forever

    def one_tick(self: engine_mod.Engine) -> None:
        seen["healthz"] = get(f"http://127.0.0.1:{port}/healthz")
        self.tick(self.clock.now())
        seen["state"] = json.loads(get(f"http://127.0.0.1:{port}/api/state")[1])
        self.stop()
        original(self)  # boot + shutdown receipts, no loop

    monkeypatch.setattr(engine_mod.Engine, "run_forever", one_tick)
    assert nc("run") == EXIT_OK
    assert seen["healthz"] == (200, "ok")
    assert seen["state"]["mode"] == "PAPER" and len(seen["state"]["positions"]) == 1
    with Ledger(env / "nightcrawler.db") as ledger:
        kinds = [r.kind for r in ledger.receipts()]
    assert "boot" in kinds and "fill" in kinds and kinds[-1] == "note"
    with pytest.raises(OSError):  # the dashboard was shut down
        get(f"http://127.0.0.1:{port}/healthz")


def test_run_refuses_a_bad_live_wallet(env, monkeypatch, capsys) -> None:
    monkeypatch.setenv("TRADING_MODE", "live")
    monkeypatch.setenv("LIVE_CONFIRM", "I_ACCEPT_REAL_MONEY_RISK")
    monkeypatch.setenv("BOT_WALLET_SECRET", "definitely-not-a-key")
    monkeypatch.setenv("DASHBOARD_TOKEN", "a-long-random-dashboard-password")
    assert nc("run", "--no-dashboard") == EXIT_CONFIG
    err = capsys.readouterr().err
    assert "definitely-not-a-key" not in err and "secret" in err.lower()


def test_run_refuses_live_without_confirmation(env, monkeypatch, capsys) -> None:
    monkeypatch.setenv("TRADING_MODE", "live")
    assert nc("run") == EXIT_CONFIG
    assert "LIVE_CONFIRM" in capsys.readouterr().err


def test_dashboard_command_serves_the_ledger(env, monkeypatch, capsys) -> None:
    port = free_port()
    monkeypatch.setenv("PORT", str(port))
    monkeypatch.setenv("DASHBOARD_TOKEN", "a-long-dashboard-token-123")
    seen: dict[str, Any] = {}

    def fake_wait(_stop: Any) -> None:
        seen["healthz"] = get(f"http://127.0.0.1:{port}/healthz")
        seen["state"] = json.loads(get(f"http://127.0.0.1:{port}/api/state?token=a-long-dashboard-token-123")[1])
        try:
            get(f"http://127.0.0.1:{port}/api/state")
        except urllib.error.HTTPError as exc:
            seen["no_token"] = exc.code

    monkeypatch.setattr(cli, "_wait_for_signal", fake_wait)
    assert nc("dashboard") == EXIT_OK
    assert seen["healthz"] == (200, "ok") and seen["state"]["mode"] == "PAPER" and seen["no_token"] == 401


def test_version_and_usage_errors(capsys) -> None:
    with pytest.raises(SystemExit) as info:
        main(["--version"])
    assert info.value.code == 0 and "nightcrawler" in capsys.readouterr().out
    with pytest.raises(SystemExit) as info:
        main(["no-such-command"])
    assert info.value.code == EXIT_USAGE


# =========================================================================== learn


def test_learn_status_before_any_learning_data(env, capsys) -> None:
    assert nc("learn", "status") == EXIT_OK
    out = capsys.readouterr().out
    assert "Collecting data, day 1" in out and "no learning data yet" in out
    assert not (env / "learn").exists()  # looking never creates anything


def test_learn_run_then_status(env, monkeypatch, capsys) -> None:
    applied: list[float] = []
    monkeypatch.setattr(learn_job, "apply_limits", lambda seconds: applied.append(seconds) or {})
    term = signal.getsignal(signal.SIGTERM)
    assert nc("learn", "run") == EXIT_OK
    assert signal.getsignal(signal.SIGTERM) == term  # its stop handlers are removed again
    out = capsys.readouterr().out
    assert "learner ok" in out and "registered 5" in out
    assert applied == []  # a person's run is theirs to limit; only the bot's own child limits itself
    assert nc("learn", "status") == EXIT_OK
    out = capsys.readouterr().out
    assert "Strategy versions (5)" in out and "random entry (control)" in out
    assert "waiting for the bot to receipt them: 6" in out and "last run" in out.lower()
    assert nc("learn", "status", "--json") == EXIT_OK
    data = json.loads(capsys.readouterr().out)
    assert data["store"]["variants"] == 5 and data["store"]["outbox"]["pending"] == 6
    assert data["card"]["state"] == "collecting" and data["last_run"]["status"] == "ok"
    assert data["enabled"] is True and data["recorder"] is None  # no bot has run here


def test_learn_with_learning_off_does_nothing(env, monkeypatch, capsys) -> None:
    monkeypatch.setenv("LEARN_ENABLED", "false")
    assert nc("learn", "run") == EXIT_OK
    assert "LEARN_ENABLED=false" in capsys.readouterr().err
    assert nc("learn", "status") == EXIT_OK
    assert "Learning is off" in capsys.readouterr().out
    assert not (env / "learn").exists()


def test_the_bots_learner_child_limits_itself_and_exits_when_the_bot_is_gone(env, monkeypatch, capsys) -> None:
    applied: list[float] = []
    monkeypatch.setattr(learn_job, "apply_limits", lambda seconds: applied.append(seconds) or {"nice": 19})
    code = nc("learn", "run", "--incremental", "--parent-pid", str(os.getppid() + 7919), "--max-seconds", "30")
    assert code == EXIT_OK and applied == [30.0]
    assert "stopped (parent gone)" in capsys.readouterr().out
