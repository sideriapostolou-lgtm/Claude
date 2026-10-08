"""Foundation tests: Settings parsing, validation, secrets and redaction."""

from __future__ import annotations

import copy
import json
import pickle
from pathlib import Path

import pytest

from nightcrawler.config import (
    LIVE_CONFIRM_PHRASE,
    ConfigError,
    Secret,
    Settings,
    load_settings,
    parse_dotenv,
    redact_url,
)
from nightcrawler.models import StrategyParams

WALLET = "4" * 88  # stand-in secret string (format is validated by wallet.py, not config)


def test_defaults_match_spec(settings: Settings) -> None:
    s = settings
    assert s.trading_mode == "paper" and not s.is_live
    assert s.paper_start_usd == 100.0
    assert s.position_pct == 0.20 and s.max_position_usd == 25.0 and s.min_position_usd == 5.0
    assert s.max_open_positions == 3
    assert s.daily_loss_limit_pct == 0.20 and s.max_drawdown_halt_pct == 0.50
    assert s.max_wallet_usd == 150.0
    assert s.sol_reserve == 0.02 and s.sol_reserve_lamports == 20_000_000
    assert s.max_price_impact_pct == 3.0
    assert s.network_fee_sol == 0.0003 and s.network_fee_lamports == 300_000
    assert s.kill_switch == "off"
    assert (s.min_age_min, s.max_age_h, s.min_mcap_usd, s.max_mcap_usd, s.min_liquidity_usd) == (
        60.0, 48.0, 100_000.0, 5_000_000.0, 30_000.0)
    assert (s.dip_pct, s.confirm_green, s.min_buy_sell_ratio) == (0.55, 2, 1.2)
    assert (s.take_profit_pct, s.partial_tp_fraction, s.trail_pct, s.stop_loss_pct) == (0.40, 0.5, 0.15, 0.18)
    assert (s.max_hold_min, s.cooldown_min) == (120.0, 30.0)
    assert s.judge_model == "claude-opus-5-5" and s.judge_effort == "low"
    assert s.judge_timeout_s == 10.0 and s.judge_cache_min == 20.0
    assert s.port == 8080
    assert (s.discovery_interval_s, s.watch_interval_s, s.position_interval_s) == (30.0, 60.0, 10.0)
    assert s.solana_rpc_url == "https://api.mainnet-beta.solana.com"
    assert s.simulate_before_send is True


def test_judge_mode_defaults_follow_key(make_settings) -> None:
    assert make_settings().judge_mode == "off"
    assert make_settings(ANTHROPIC_API_KEY="sk-ant-test-123456").judge_mode == "required"
    assert make_settings(ANTHROPIC_API_KEY="sk-ant-test-123456", JUDGE_MODE="advisory").judge_mode == "advisory"
    with pytest.raises(ConfigError, match="JUDGE_MODE=required requires ANTHROPIC_API_KEY"):
        make_settings(JUDGE_MODE="required")


def test_jupiter_base_url_auto(make_settings) -> None:
    assert make_settings().jupiter_base_url == "https://lite-api.jup.ag"
    s = make_settings(JUPITER_API_KEY="jupkey-abcdef")
    assert s.jupiter_base_url == "https://api.jup.ag"
    assert make_settings(JUPITER_BASE_URL="https://example.org/").jupiter_base_url == "https://example.org"


def test_parsing_types_and_blank_values(make_settings) -> None:
    s = make_settings(POSITION_PCT="0.1", MAX_OPEN_POSITIONS="5", SIMULATE_BEFORE_SEND="no",
                      KILL_SWITCH="STOP", TRADING_MODE="Paper", PORT="9000", CONFIRM_GREEN="3.0")
    assert s.position_pct == 0.1 and s.max_open_positions == 5 and s.simulate_before_send is False
    assert s.kill_switch == "stop" and s.trading_mode == "paper" and s.port == 9000 and s.confirm_green == 3
    assert isinstance(s.data_dir, Path)
    # blank values fall back to defaults (Railway sets empty variables sometimes)
    s2 = Settings.from_env({"POSITION_PCT": "  ", "DATA_DIR": ""})
    assert s2.position_pct == 0.20 and s2.data_dir == Path("./data")


def test_validation_collects_all_problems(make_settings) -> None:
    with pytest.raises(ConfigError) as ei:
        make_settings(POSITION_PCT="20", MAX_PRICE_IMPACT_PCT="0", JUDGE_EFFORT="maybe", PORT="0")
    text = str(ei.value)
    assert len(ei.value.problems) == 4
    assert "POSITION_PCT=20.0 must be <= 1 (a FRACTION: 0.20 means 20%)" in text
    assert "MAX_PRICE_IMPACT_PCT" in text and "PERCENT" in text
    assert "JUDGE_EFFORT='maybe' must be one of low, medium, high, xhigh, max" in text
    # KILL_SWITCH never refuses to boot: a garbled value fails SAFE to "stop" (see the review-fix tests)
    assert make_settings(KILL_SWITCH="maybe").kill_switch == "stop"


@pytest.mark.parametrize("env,needle", [
    ({"POSITION_PCT": "abc"}, "expected a number"),
    ({"POSITION_PCT": "20%"}, "without '%'"),
    ({"MAX_OPEN_POSITIONS": "2.5"}, "whole number"),
    ({"SIMULATE_BEFORE_SEND": "perhaps"}, "true/false"),
    ({"DIP_PCT": "nan"}, "finite"),
])
def test_bad_values_are_reported(env, needle) -> None:
    with pytest.raises(ConfigError, match=needle):
        Settings.from_env(env)


def test_cross_field_rules(make_settings) -> None:
    with pytest.raises(ConfigError, match="MIN_POSITION_USD must be <= MAX_POSITION_USD"):
        make_settings(MIN_POSITION_USD=30)
    with pytest.raises(ConfigError, match="MIN_MCAP_USD must be < MAX_MCAP_USD"):
        make_settings(MIN_MCAP_USD=6_000_000)
    with pytest.raises(ConfigError, match="MIN_AGE_MIN"):
        make_settings(MIN_AGE_MIN=3000, MAX_AGE_H=48)
    with pytest.raises(ConfigError, match="SOLANA_RPC_URL"):
        make_settings(SOLANA_RPC_URL="ftp://nope")


def test_live_requires_confirmation_and_wallet(make_settings) -> None:
    with pytest.raises(ConfigError) as ei:
        make_settings(TRADING_MODE="live")
    assert any(LIVE_CONFIRM_PHRASE in p for p in ei.value.problems)
    assert any("BOT_WALLET_SECRET" in p for p in ei.value.problems)
    with pytest.raises(ConfigError):
        make_settings(TRADING_MODE="live", LIVE_CONFIRM="yes please", BOT_WALLET_SECRET=WALLET)
    s = make_settings(TRADING_MODE="live", LIVE_CONFIRM=LIVE_CONFIRM_PHRASE, BOT_WALLET_SECRET=WALLET,
                      DASHBOARD_TOKEN="a-long-random-dashboard-password")
    assert s.is_live and s.bot_wallet_secret.reveal() == WALLET


def test_secrets_never_leak(make_settings) -> None:
    s = make_settings(TRADING_MODE="live", LIVE_CONFIRM=LIVE_CONFIRM_PHRASE, BOT_WALLET_SECRET=WALLET,
                      ANTHROPIC_API_KEY="sk-ant-api03-SECRETSECRET", JUPITER_API_KEY="jup-SECRET-KEY",
                      DASHBOARD_TOKEN="dash-SECRET", X_BEARER_TOKEN="xbearer-SECRET",
                      SOLANA_RPC_URL="https://mainnet.helius-rpc.com/?api-key=HELIUSSECRET")
    secrets = [WALLET, "sk-ant-api03-SECRETSECRET", "jup-SECRET-KEY", "dash-SECRET", "xbearer-SECRET",
               "HELIUSSECRET"]
    for text in (repr(s), str(s), json.dumps(s.public_dict(), default=str)):
        for secret in secrets:
            assert secret not in text
    pub = s.public_dict()
    assert pub["bot_wallet_secret_set"] is True and pub["anthropic_api_key_set"] is True
    assert "bot_wallet_secret" not in pub and "live_confirm" not in pub and pub["live_confirmed"] is True
    assert pub["solana_rpc_url"] == "https://mainnet.helius-rpc.com/?api-key=***"
    assert set(secrets) <= set(s.secret_values())


def test_secret_wrapper() -> None:
    sec = Secret("hunter2-long")
    assert str(sec) == "***" and repr(sec) == "Secret('***')" and f"{sec}" == "***"
    assert sec.reveal() == "hunter2-long" and bool(sec) and not Secret("")
    assert copy.deepcopy(sec) is sec
    with pytest.raises(TypeError):
        pickle.dumps(sec)


def test_replace_revalidates_and_wraps_secrets(settings: Settings) -> None:
    s2 = settings.replace(position_pct=0.1, anthropic_api_key="sk-ant-zzzzzzzz", judge_mode="advisory")
    assert s2.position_pct == 0.1 and isinstance(s2.anthropic_api_key, Secret) and s2.judge_mode == "advisory"
    with pytest.raises(ConfigError):
        settings.replace(position_pct=5)
    with pytest.raises(dataclasses_frozen_error()):
        settings.position_pct = 0.3  # type: ignore[misc]


def dataclasses_frozen_error():
    import dataclasses

    return dataclasses.FrozenInstanceError


def test_paths_and_strategy_params(settings: Settings, tmp_data_dir: Path) -> None:
    assert settings.data_dir == tmp_data_dir
    assert settings.db_path == tmp_data_dir / "nightcrawler.db"
    assert settings.kill_file == tmp_data_dir / "KILL"
    assert settings.dataset_dir == tmp_data_dir / "dataset"
    sp = settings.strategy_params()
    assert isinstance(sp, StrategyParams)
    assert sp.dip_pct == settings.dip_pct and sp.dip_lookback_h == settings.dip_lookback_h
    assert sp == StrategyParams()  # Settings defaults == StrategyParams defaults


def test_describe_covers_every_field() -> None:
    rows = Settings.describe()
    envs = {r["env"] for r in rows}
    assert {"TRADING_MODE", "BOT_WALLET_SECRET", "POSITION_PCT", "PORT", "JUDGE_MODEL"} <= envs
    assert all(r["help"] and r["unit"] for r in rows)
    assert {r["env"] for r in rows if r["secret"]} == {
        "ANTHROPIC_API_KEY", "JUPITER_API_KEY", "BOT_WALLET_SECRET", "X_BEARER_TOKEN", "DASHBOARD_TOKEN"}


def test_env_example_lists_every_setting() -> None:
    example = Path(__file__).resolve().parents[1] / ".env.example"
    keys = set(parse_dotenv(example)) | {
        line.lstrip("# ").split("=", 1)[0].strip()
        for line in example.read_text().splitlines() if line.startswith("# ") and "=" in line
    }
    missing = {r["env"] for r in Settings.describe()} - keys
    assert not missing, f".env.example is missing {sorted(missing)}"
    # the example must never contain a real-looking secret value
    values = parse_dotenv(example)
    for r in Settings.describe():
        if r["secret"]:
            assert not values.get(r["env"]), f"{r['env']} must be empty in .env.example"


def test_parse_dotenv_and_load_settings(tmp_path: Path) -> None:
    f = tmp_path / ".env"
    f.write_text("# comment\nexport POSITION_PCT=0.1\nPORT='9001'\nKILL_SWITCH=stop # inline\n"
                 "JUDGE_MODEL=\"claude-haiku-5-5\"\nBROKEN LINE\n")
    assert parse_dotenv(f) == {"POSITION_PCT": "0.1", "PORT": "9001", "KILL_SWITCH": "stop",
                               "JUDGE_MODEL": "claude-haiku-5-5"}
    assert parse_dotenv(tmp_path / "missing.env") == {}
    s = load_settings(f, env={"PORT": "9002", "DATA_DIR": str(tmp_path)})
    assert s.port == 9002  # real env wins over the file
    assert s.position_pct == 0.1 and s.kill_switch == "stop" and s.judge_model == "claude-haiku-5-5"


def test_redact_url() -> None:
    assert redact_url("https://x.io/?api-key=abc&cluster=main") == "https://x.io/?api-key=***&cluster=main"
    assert redact_url("https://api.mainnet-beta.solana.com") == "https://api.mainnet-beta.solana.com"
    assert redact_url("https://x.io/rpc?token=t1") == "https://x.io/rpc?token=***"


# --------------------------------------------------------------------------- review fixes


@pytest.mark.parametrize("raw,expected", [
    ("sell-all", "sell_all"), ("sell all", "sell_all"), ("Sell All", "sell_all"), (" SELL_ALL ", "sell_all"),
    ("STOP", "stop"), ("off", "off"),
    ("sel_all", "stop"), ("maybe", "stop"),  # garbled: fail SAFE (no new entries), never refuse to boot
])
def test_kill_switch_is_normalized_and_never_blocks_startup(raw, expected, tmp_path) -> None:
    from nightcrawler.risk import RiskManager

    s = Settings.from_env({"KILL_SWITCH": raw, "DATA_DIR": str(tmp_path)})
    assert s.kill_switch == expected
    assert RiskManager(s, None, None).kill_mode() == expected  # type: ignore[arg-type]


QUICKNODE = "https://x.solana-mainnet.quiknode.pro/abcdef0123456789SECRETKEY/"
ALCHEMY = "https://solana-mainnet.g.alchemy.com/v2/AlchemyKey0123456789abcdef"


@pytest.mark.parametrize("url,key", [(QUICKNODE, "abcdef0123456789SECRETKEY"),
                                     (ALCHEMY, "AlchemyKey0123456789abcdef")])
def test_rpc_keys_in_the_url_path_are_secret(make_settings, url, key) -> None:
    from nightcrawler.http import HttpError

    s = make_settings(SOLANA_RPC_URL=url)
    assert key not in json.dumps(s.public_dict(), default=str) and key not in repr(s)
    assert key in s.secret_values()
    assert s.public_dict()["solana_rpc_url"].startswith("https://") and "***" in s.public_dict()["solana_rpc_url"]
    err = HttpError("HTTP 429", url=url, status=429, secret_paths=True)
    assert key not in str(err) and key not in err.url


def test_http_errors_from_a_path_key_rpc_never_show_the_key(make_settings) -> None:
    from fakes import FakeClock, FakeHttp
    from nightcrawler.http import HttpClient, HttpError

    s = make_settings(SOLANA_RPC_URL=QUICKNODE)
    fake = FakeHttp()
    fake.register("quiknode.pro", {"error": "slow down"}, status=429, method="POST")
    client = HttpClient.from_settings(s, session=fake, clock=FakeClock(0.0), max_retries=0)
    with pytest.raises(HttpError) as ei:
        client.post_json(s.solana_rpc_url, json={"method": "getHealth"})
    assert "SECRETKEY" not in str(ei.value) and "SECRETKEY" not in ei.value.url
    assert "x.solana-mainnet.quiknode.pro" in str(ei.value)


def test_live_mode_requires_a_dashboard_token_unless_bound_to_loopback(make_settings) -> None:
    live = {"TRADING_MODE": "live", "LIVE_CONFIRM": LIVE_CONFIRM_PHRASE, "BOT_WALLET_SECRET": WALLET}
    with pytest.raises(ConfigError, match="DASHBOARD_TOKEN"):
        make_settings(**live)
    assert make_settings(**live, DASHBOARD_TOKEN="a-long-random-dashboard-password").is_live
    assert make_settings(**live, DASHBOARD_HOST="127.0.0.1").is_live
    assert make_settings(DASHBOARD_HOST="0.0.0.0").trading_mode == "paper"  # paper needs no token


def test_take_profit_written_as_percent_is_rejected_with_the_fraction_hint(make_settings) -> None:
    with pytest.raises(ConfigError, match="TAKE_PROFIT_PCT=40.0 must be <= 10.*FRACTION"):
        make_settings(TAKE_PROFIT_PCT="40")
    assert make_settings(TAKE_PROFIT_PCT="0.4").take_profit_pct == 0.4
    assert make_settings(TAKE_PROFIT_PCT="2.0").take_profit_pct == 2.0
