"""BOT_WALLET_MODE=generated (nightcrawler.broker.keystore): the bot makes its own wallet once, keeps the key in
DATA_DIR/wallet/ (folder 0700, file 0600), never replaces it, never makes one where it could be lost, and the key
never reaches any output surface: logs, receipts, kv, the ledger file, /api/*, the page, exceptions, repr,
the CLI or a child process's environment. Only the PUBLIC address is shown.

Assertions about leaks report WHICH encoding leaked, never the value, so a failing test prints no key."""

from __future__ import annotations

import base64
import contextlib
import copy
import http.client
import io
import json
import logging
import os
import pickle
import sqlite3
import stat
import sys
from pathlib import Path
from typing import Any, Callable, Iterator

import pytest

pytest.importorskip("solders")

from fakes import FakeClock, FakeHttp  # noqa: E402
from nightcrawler import cli  # noqa: E402
from nightcrawler.base58 import b58encode  # noqa: E402
from nightcrawler.broker import keystore  # noqa: E402
from nightcrawler.broker.keystore import (  # noqa: E402
    KEY_FILE,
    KV_GENERATED,
    KeystoreError,
    KeystoreExists,
    key_path,
    resolve_wallet,
)
from nightcrawler.config import LIVE_CONFIRM_PHRASE, ConfigError, Settings  # noqa: E402
from nightcrawler.dashboard import DashboardServer, build_state  # noqa: E402
from nightcrawler.ledger import Ledger  # noqa: E402
from nightcrawler.logging_setup import get_logger, setup_logging  # noqa: E402
from nightcrawler.teamroom import TeamRoom  # noqa: E402
from world import make_world  # noqa: E402

STRONG_TOKEN = "k3y-st0re-dashboard-passw0rd-7f1c9a2b4d6e"
#: A valid on-curve address that is not the bot's (WITHDRAW_TO in these tests).
OWNER = "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM"


# --------------------------------------------------------------------------- helpers


def secret_forms(secret: bytes) -> dict[str, str]:
    """Every text encoding of the 64-byte key and of its 32-byte seed someone could print by mistake."""
    forms: dict[str, str] = {}
    for label, part in (("key", secret), ("seed", secret[:32])):
        forms[f"{label}.base58"] = b58encode(part)
        forms[f"{label}.hex"] = part.hex()
        forms[f"{label}.HEX"] = part.hex().upper()
        forms[f"{label}.base64"] = base64.b64encode(part).decode("ascii")
        forms[f"{label}.base64url"] = base64.urlsafe_b64encode(part).decode("ascii")
        forms[f"{label}.json"] = json.dumps(list(part))
        forms[f"{label}.json_compact"] = json.dumps(list(part), separators=(",", ":"))
        forms[f"{label}.ints"] = ",".join(str(b) for b in part[:16])  # a slice of the byte list
    return forms


def leaks(blob: str | bytes, secret: bytes) -> list[str]:
    """Names of the key encodings found in ``blob`` (bytes also checks the raw key and seed)."""
    found = []
    if isinstance(blob, bytes):
        found += [name for name, raw in (("key.raw", secret), ("seed.raw", secret[:32])) if raw in blob]
        text = blob.decode("latin-1")
    else:
        text = blob
    found += [name for name, form in secret_forms(secret).items() if form in text]
    return found


def read_key(data_dir: Path) -> bytes:
    """The throwaway test key (only to look for it elsewhere; never printed)."""
    return bytes(json.loads(key_path(data_dir).read_text()))


def mode_of(path: Path) -> int:
    return stat.S_IMODE(os.lstat(path).st_mode)


@contextlib.contextmanager
def only_redacting_log_handlers() -> Iterator[None]:
    """While a test logs a (throwaway) key on purpose, only nightcrawler's redacting handlers may see the
    records: pytest's own log capture would otherwise print them if the test failed."""
    root = logging.getLogger()
    others = [h for h in root.handlers if not getattr(h, "_nightcrawler", False)]
    for handler in others:
        root.removeHandler(handler)
    try:
        yield
    finally:
        for handler in others:
            root.addHandler(handler)


def drop_nightcrawler_log_handlers() -> None:
    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, "_nightcrawler", False):
            root.removeHandler(handler)


@pytest.fixture
def ledger(tmp_path: Path, fake_clock: FakeClock) -> Iterator[Ledger]:
    with Ledger(tmp_path / "nc.db", clock=fake_clock) as led:
        yield led


@pytest.fixture
def generated(make_settings: Callable[..., Settings]) -> Settings:
    return make_settings(BOT_WALLET_MODE="generated")


# --------------------------------------------------------------------------- made once, kept private


def test_the_first_start_makes_one_private_key_and_receipts_only_its_address(generated: Settings,
                                                                              ledger: Ledger) -> None:
    wallet = resolve_wallet(generated, ledger, env={})
    assert wallet is not None
    path = key_path(generated.data_dir)
    assert path.is_file() and mode_of(path) == 0o600 and mode_of(path.parent) == 0o700
    assert sorted(p.name for p in path.parent.iterdir()) == [KEY_FILE]  # no temporary file left behind
    assert ledger.get_kv("wallet.pubkey") == ledger.get_kv(KV_GENERATED) == wallet.pubkey()
    created = [r for r in ledger.receipts() if r.kind == "wallet_created"]
    assert len(created) == 1 and created[0].payload == {"pubkey": wallet.pubkey(), "mode": "generated",
                                                        "made_this_start": True}
    secret = read_key(generated.data_dir)
    assert len(secret) == 64 and b58encode(secret[32:]) == wallet.pubkey()

    before = path.read_bytes()
    again = resolve_wallet(generated, ledger, env={})  # every later start loads the same key
    assert again is not None and again.pubkey() == wallet.pubkey() and path.read_bytes() == before
    assert len([r for r in ledger.receipts() if r.kind == "wallet_created"]) == 1


def test_each_bot_gets_a_fresh_random_key_that_signs(make_settings: Callable[..., Settings], tmp_path: Path) -> None:
    from solders.keypair import Keypair

    a = keystore.create(tmp_path / "a")
    b = keystore.create(tmp_path / "b")
    assert a.pubkey() != b.pubkey()
    secret = read_key(tmp_path / "a")
    keypair = Keypair.from_bytes(secret)
    message = b"nightcrawler"
    assert keypair.sign_message(message).verify(keypair.pubkey(), message)
    assert str(keypair.pubkey()) == a.pubkey()


def test_an_existing_key_is_never_replaced(generated: Settings, ledger: Ledger) -> None:
    wallet = resolve_wallet(generated, ledger, env={})
    assert wallet is not None
    path = key_path(generated.data_dir)
    original = path.read_bytes()
    with pytest.raises(KeystoreExists):
        keystore.create(generated.data_dir)
    assert path.read_bytes() == original

    path.write_text("not a key at all\n")  # damaged: the bot stops instead of making a new one
    with pytest.raises(KeystoreError, match="damaged") as caught:
        resolve_wallet(generated, ledger, env={})
    assert "not a key at all" not in str(caught.value)
    assert path.read_text() == "not a key at all\n"
    path.write_text(json.dumps([7] * 64))  # 64 bytes whose public half does not match the seed
    with pytest.raises(KeystoreError, match="damaged"):
        resolve_wallet(generated, ledger, env={})


def test_a_link_or_a_folder_in_place_of_the_key_is_refused(generated: Settings, tmp_path: Path) -> None:
    folder = key_path(generated.data_dir).parent
    folder.mkdir(parents=True)
    elsewhere = tmp_path / "elsewhere.json"
    keystore.create(tmp_path / "other")
    elsewhere.write_bytes(key_path(tmp_path / "other").read_bytes())
    key_path(generated.data_dir).symlink_to(elsewhere)
    with pytest.raises(KeystoreError, match="not a regular file"):
        resolve_wallet(generated, env={})
    key_path(generated.data_dir).unlink()
    key_path(generated.data_dir).mkdir()
    with pytest.raises(KeystoreError, match="not a regular file"):
        resolve_wallet(generated, env={})


def test_loose_permissions_are_tightened(generated: Settings) -> None:
    wallet = resolve_wallet(generated, env={})
    path = key_path(generated.data_dir)
    os.chmod(path, 0o644)
    os.chmod(path.parent, 0o755)
    again = resolve_wallet(generated, env={})
    assert again is not None and wallet is not None and again.pubkey() == wallet.pubkey()
    assert mode_of(path) == 0o600 and mode_of(path.parent) == 0o700


def test_a_racing_second_process_loads_the_first_ones_key(generated: Settings, monkeypatch: pytest.MonkeyPatch
                                                          ) -> None:
    first = keystore.create(generated.data_dir)
    calls = []
    real_load = keystore.load

    def load_misses_once(data_dir: Any, redaction_filter: Any = None) -> Any:  # it looked before the other wrote
        calls.append(1)
        return None if len(calls) == 1 else real_load(data_dir, redaction_filter)

    monkeypatch.setattr(keystore, "load", load_misses_once)
    wallet, created = keystore.load_or_create(generated.data_dir)
    assert not created and wallet.pubkey() == first.pubkey()


# --------------------------------------------------------------------------- never made where it could be lost


def test_live_mode_never_makes_a_wallet(make_settings: Callable[..., Settings], ledger: Ledger) -> None:
    live = make_settings(TRADING_MODE="live", LIVE_CONFIRM=LIVE_CONFIRM_PHRASE, BOT_WALLET_MODE="generated",
                         DASHBOARD_TOKEN=STRONG_TOKEN)
    with pytest.raises(KeystoreError, match="PAPER mode"):
        resolve_wallet(live, ledger, env={})
    assert not key_path(live.data_dir).exists() and ledger.receipts() == []
    keystore.create(live.data_dir)  # made in paper mode earlier: live mode uses it
    wallet = resolve_wallet(live, ledger, env={})
    assert wallet is not None and ledger.get_kv("wallet.pubkey") == wallet.pubkey()


def test_a_lost_key_file_is_never_silently_replaced(generated: Settings, ledger: Ledger) -> None:
    wallet = resolve_wallet(generated, ledger, env={})
    assert wallet is not None
    key_path(generated.data_dir).unlink()
    with pytest.raises(KeystoreError, match=wallet.pubkey()):
        resolve_wallet(generated, ledger, env={})
    assert not key_path(generated.data_dir).exists()


def test_on_railway_the_key_is_made_only_on_the_volume(generated: Settings, ledger: Ledger) -> None:
    railway = {"RAILWAY_PROJECT_ID": "p", "RAILWAY_SERVICE_ID": "s"}
    with pytest.raises(KeystoreError, match="no volume is attached"):
        resolve_wallet(generated, ledger, env=railway)
    with pytest.raises(KeystoreError, match="not on the Railway volume"):
        resolve_wallet(generated, ledger, env={**railway, "RAILWAY_VOLUME_MOUNT_PATH": "/somewhere/else"})
    assert not key_path(generated.data_dir).exists()
    volume = {**railway, "RAILWAY_VOLUME_MOUNT_PATH": str(generated.data_dir.parent)}
    assert resolve_wallet(generated, ledger, env=volume) is not None
    assert keystore.storage_problem(generated.data_dir, {}) is None  # not on Railway: the operator owns the disk


def test_build_app_refuses_to_start_rather_than_replace_or_lose_a_key(generated: Settings, fake_clock: FakeClock
                                                                        ) -> None:
    from nightcrawler.engine import build_app

    app = build_app(generated, fake_clock, session=FakeHttp())
    try:
        assert app.wallet is not None and app.broker.taker == app.wallet.pubkey()  # paper quotes as the bot wallet
    finally:
        app.close()
    key_path(generated.data_dir).write_text("[1, 2, 3]")
    with pytest.raises(KeystoreError):
        build_app(generated, fake_clock, session=FakeHttp())


# --------------------------------------------------------------------------- settings


def test_settings_refuse_an_ambiguous_wallet_and_never_echo_values(make_settings: Callable[..., Settings]) -> None:
    pasted = "4wBqpZM9xaSheZzJSMawUKKwhdpChKbZ5eu5ky4Vigw1t7Wv5jNzqJmsRcFVw8NhpWxnJ8u5fE3ygVJgLFrTTXpo"
    with pytest.raises(ConfigError, match="both set") as caught:
        make_settings(BOT_WALLET_MODE="generated", BOT_WALLET_SECRET=pasted)
    assert pasted not in str(caught.value)
    with pytest.raises(ConfigError, match="BOT_WALLET_MODE must be env or generated") as caught:
        make_settings(BOT_WALLET_MODE=pasted)
    assert pasted not in str(caught.value)
    with pytest.raises(ConfigError, match="WITHDRAW_TO must be a Solana address") as caught:
        make_settings(WITHDRAW_TO=pasted)  # a private key pasted into the wrong box is never repeated
    assert pasted not in str(caught.value)
    live = make_settings(TRADING_MODE="live", LIVE_CONFIRM=LIVE_CONFIRM_PHRASE, BOT_WALLET_MODE=" Generated ",
                         DASHBOARD_TOKEN=STRONG_TOKEN)
    assert live.is_live and live.bot_wallet_mode == "generated" and not live.bot_wallet_secret
    with pytest.raises(ConfigError, match="BOT_WALLET_MODE=generated"):
        make_settings(TRADING_MODE="live", LIVE_CONFIRM=LIVE_CONFIRM_PHRASE, DASHBOARD_TOKEN=STRONG_TOKEN)
    assert make_settings().bot_wallet_mode == "env" and make_settings(WITHDRAW_TO=f" {OWNER} ").withdraw_to == OWNER


# --------------------------------------------------------------------------- secrecy: every output surface


def _rpc_handler(fixture: Any) -> Callable[[Any], Any]:
    """Solana JSON-RPC for the world plus what the bot wallet and the paper withdrawal read."""
    blockhash = b58encode(bytes(range(1, 33)))

    def handle(req: Any) -> Any:
        method, params = req.json.get("method"), req.json.get("params") or []
        envelope = {"jsonrpc": "2.0", "id": req.json.get("id")}
        if method == "getBalance":
            return {**envelope, "result": {"context": {"slot": 1}, "value": 300_000_000}}
        if method == "getLatestBlockhash":
            return {**envelope, "result": {"context": {"slot": 1},
                                           "value": {"blockhash": blockhash, "lastValidBlockHeight": 500}}}
        if method == "getFeeForMessage":
            return {**envelope, "result": {"context": {"slot": 1}, "value": 5000}}
        if method == "getMinimumBalanceForRentExemption":
            return {**envelope, "result": 890_880}
        if method == "getAccountInfo" and params and params[0] == OWNER:
            return {**envelope, "result": {"context": {"slot": 1}, "value": None}}
        return fixture

    return handle


def test_the_key_never_reaches_any_output_surface(make_settings: Callable[..., Settings], fake_clock: FakeClock,
                                                  load_fixture: Callable[[str], Any], tmp_path: Path,
                                                  monkeypatch: pytest.MonkeyPatch,
                                                  capsys: pytest.CaptureFixture[str]) -> None:
    from nightcrawler.engine import build_app
    from nightcrawler.learn.job import learner_command, learner_env

    settings = make_settings(BOT_WALLET_MODE="generated", WITHDRAW_TO=OWNER, DASHBOARD_TOKEN=STRONG_TOKEN,
                             LOG_LEVEL="DEBUG")
    fake = FakeHttp()
    make_world(fake, fake_clock)
    fake.register("api.mainnet-beta.solana.com", _rpc_handler(load_fixture("rpc_getAccountInfo_mint")),
                  method="POST")
    logs = io.StringIO()
    filt = setup_logging("DEBUG", settings.secret_values(), stream=logs)
    stack = contextlib.ExitStack()
    stack.enter_context(only_redacting_log_handlers())
    try:
        app = build_app(settings, fake_clock, session=fake, redaction_filter=filt)
        assert app.wallet is not None and app.engine.withdraw is not None
        pubkey = app.wallet.pubkey()
        secret = read_key(settings.data_dir)
        for _ in range(4):  # trading, the bot-wallet balance reading and the paper withdrawal all run
            app.engine.tick(fake_clock.now())
            fake_clock.advance(700)
        assert app.ledger.get_kv("withdraw.state")["status"] == "paper"
        assert app.ledger.get_kv("bot_wallet.balance")["address"] == pubkey
        # even a careless log line with the key in it is redacted (every encoding was registered on load)
        careless = get_logger("nightcrawler.test")
        forms = secret_forms(secret)
        for name in ("key.base58", "seed.base58", "key.hex", "seed.hex", "key.base64", "seed.base64", "key.json",
                     "key.json_compact", "seed.json"):
            careless.warning("oops %s", forms[name])
        careless.warning("wallet %r %s", app.wallet, app.wallet)
        try:
            pickle.dumps(app.wallet)
        except TypeError as exc:
            careless.exception("pickle refused: %s", exc)
        with pytest.raises(TypeError):
            copy.copy(app.wallet)

        surfaces: dict[str, str | bytes] = {
            "repr": repr(app.wallet) + str(app.wallet) + repr(settings) + json.dumps(settings.public_dict()),
            "receipts": "\n".join(json.dumps(r.to_dict()) for r in app.ledger.receipts()),
            "child_env": json.dumps(learner_env(settings)) + json.dumps(learner_command(1, 60)),
            "os_environ": json.dumps(dict(os.environ)),
        }
        exported = tmp_path / "receipts.jsonl"
        app.ledger.export_receipts(exported)
        surfaces["receipts_export"] = exported.read_text()
        with contextlib.closing(sqlite3.connect(f"file:{settings.db_path}?mode=ro", uri=True)) as db:
            surfaces["kv"] = json.dumps(db.execute("SELECT key, value FROM kv").fetchall())

        # the dashboard: every route, with the token
        cache: dict[str, Any] = {}
        team = TeamRoom(settings, ledger=app.ledger, clock=fake_clock, environ={})
        server = DashboardServer(settings, lambda: build_state(app.ledger, settings, fake_clock.now(), cache),
                                 host="127.0.0.1", port=0, team=team)
        server.start()
        try:
            for route in ("/", "/api/page", "/api/state", "/api/team", "/healthz", "/team"):
                conn = http.client.HTTPConnection("127.0.0.1", server.bound_port, timeout=10)
                try:
                    conn.request("GET", f"{route}?token={STRONG_TOKEN}")
                    res = conn.getresponse()
                    body = res.read()
                finally:
                    conn.close()
                surfaces[f"http{route}"] = body
                if route == "/api/page":
                    page = json.loads(body)
                    assert page["wallet"]["address"] == pubkey  # the PUBLIC address is shown ...
                    assert page["withdraw"]["status"] == "paper" and "Nothing was sent" in page["withdraw"]["text"]
        finally:
            server.stop()
    finally:
        app.close()
        drop_nightcrawler_log_handlers()
        stack.close()

    surfaces["logs"] = logs.getvalue()
    assert pubkey in surfaces["logs"] and "[REDACTED]" in surfaces["logs"]  # ... and the key is not
    db_bytes = settings.db_path.read_bytes()
    wal = Path(f"{settings.db_path}-wal")
    surfaces["ledger_file"] = db_bytes + (wal.read_bytes() if wal.exists() else b"")
    receipts = json.loads(json.dumps([json.loads(line) for line in surfaces["receipts_export"].splitlines()]))
    assert any(r["kind"] == "wallet_created" and r["payload"]["pubkey"] == pubkey for r in receipts)

    # the CLI: wallet show (address only), config, and wallet new refusing to print a key in this mode
    env = {"DATA_DIR": str(settings.data_dir), "BOT_WALLET_MODE": "generated", "WITHDRAW_TO": OWNER}
    for name in ("BOT_WALLET_SECRET", "BOT_WALLET_MODE", "WITHDRAW_TO", "TRADING_MODE"):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)

    class Jupiter:
        def holdings(self, address: str) -> Any:
            from nightcrawler.models import Balances

            return Balances(sol_lamports=300_000_000, tokens={})

        def sol_price_usd(self) -> float:
            return 150.0

        def prices(self, mints: list[str]) -> dict[str, float]:
            return {}

    monkeypatch.setattr(cli, "_sources", lambda *_a, **_k: type("S", (), {"jupiter": Jupiter()})())
    capsys.readouterr()
    assert cli.main(["--env-file", os.devnull, "wallet", "show"]) == 0
    assert cli.main(["--env-file", os.devnull, "config", "--json"]) == 0
    assert cli.main(["--env-file", os.devnull, "wallet", "new"]) == cli.EXIT_USAGE
    out = capsys.readouterr()
    surfaces["cli"] = out.out + out.err
    assert f"address: {pubkey}" in out.out
    drop_nightcrawler_log_handlers()  # the CLI runs installed their own

    leaked = {name: found for name, blob in surfaces.items() if (found := leaks(blob, secret))}
    assert not leaked, f"the bot's key leaked into: {leaked}"
    assert not any(secret_forms(secret)["key.base58"] in v for v in os.environ.values())


def test_errors_about_a_damaged_key_file_never_quote_it(generated: Settings) -> None:
    keystore.create(generated.data_dir)
    path = key_path(generated.data_dir)
    secret = read_key(generated.data_dir)
    path.write_text(json.dumps(list(secret))[:-5])  # cut short: still mostly the key
    with pytest.raises(KeystoreError) as caught:
        resolve_wallet(generated, env={})
    text = str(caught.value) + repr(caught.value) + str(caught.value.__cause__) + str(caught.value.__context__)
    assert not leaks(text, secret) and caught.value.__cause__ is None


def test_the_learner_child_never_inherits_a_key(make_settings: Callable[..., Settings]) -> None:
    from nightcrawler.learn.job import CHILD_SETTINGS, learner_env

    pasted = "4wBqpZM9xaSheZzJSMawUKKwhdpChKbZ5eu5ky4Vigw1t7Wv5jNzqJmsRcFVw8NhpWxnJ8u5fE3ygVJgLFrTTXpo"
    settings = make_settings(BOT_WALLET_SECRET=pasted)
    base = {"PATH": "/usr/bin", "BOT_WALLET_SECRET": pasted, "BOT_WALLET_MODE": "generated", "HOME": "/root"}
    env = learner_env(settings, base=base)
    assert pasted not in json.dumps(env) and "BOT_WALLET_SECRET" not in env and "BOT_WALLET_MODE" not in env
    assert not {"bot_wallet_secret", "bot_wallet_mode", "withdraw_to"} & set(CHILD_SETTINGS)


def test_only_the_cli_process_reads_the_key_file_it_needs(generated: Settings) -> None:
    """``wallet show`` reads the bot's own key file to print its address, and never makes one."""
    assert cli._wallet_pubkey(generated) is None and not key_path(generated.data_dir).exists()
    wallet = keystore.create(generated.data_dir)
    assert cli._wallet_pubkey(generated) == wallet.pubkey()


def test_safe_mode_never_switches_the_wallet() -> None:
    assert {"BOT_WALLET_MODE", "BOT_WALLET_SECRET"} <= cli.SAFE_MODE_KEEP


def test_the_secret_text_of_a_solders_keypair_is_never_built_by_the_keystore() -> None:
    """``str(Keypair)`` IS the base58 secret, so the keystore source never formats a keypair."""
    source = Path(keystore.__file__).read_text()
    assert "str(keypair" not in source and "{keypair" not in source and "%s\", keypair" not in source
    assert "secret_base58" not in source  # the one method that reveals a Wallet's key (for `wallet new` only)


def test_logged_records_cannot_carry_the_key_even_from_tracebacks(generated: Settings) -> None:
    logs = io.StringIO()
    filt = setup_logging("INFO", [], stream=logs)
    try:
        with only_redacting_log_handlers():
            resolve_wallet(generated, redaction_filter=filt, env={})
            secret = read_key(generated.data_dir)
            log = get_logger("nightcrawler.test")
            try:
                raise ValueError(f"boom {b58encode(secret)} {secret.hex()}")
            except ValueError:
                log.exception("failed")
    finally:
        drop_nightcrawler_log_handlers()
    assert not leaks(logs.getvalue(), secret) and "[REDACTED]" in logs.getvalue()
    assert sys.modules["nightcrawler.broker.keystore"] is keystore
