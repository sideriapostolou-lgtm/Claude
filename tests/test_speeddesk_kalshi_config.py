"""Owner-authorized Kalshi companion limits and secret handling; never enables local trading."""

from __future__ import annotations

import json

import pytest

from nightcrawler.config import ConfigError, Secret, Settings
from nightcrawler.logging_setup import redact_text


def test_kalshi_companion_ships_paper_with_exact_owner_ceiling_defaults() -> None:
    settings = Settings()
    assert settings.speeddesk_kalshi_mode == "paper"
    assert settings.speeddesk_kalshi_account_type == "unknown"
    assert settings.speeddesk_kalshi_live_confirm is None
    assert settings.speeddesk_kalshi_resume_token is None
    assert settings.speeddesk_kalshi_integrity_reset_token is None
    assert settings.kalshi_key_id is None and settings.kalshi_private_key is None
    assert (settings.speeddesk_kalshi_window_usd, settings.speeddesk_kalshi_open_usd,
            settings.speeddesk_kalshi_day_stop_usd, settings.speeddesk_kalshi_total_stop_usd) == (10, 20, 6, 10)
    assert settings.speeddesk_kalshi_cutoff_s == 180
    assert settings.speeddesk_kalshi_lock_s == 240 and settings.speeddesk_kalshi_lock_max_price == .97
    assert settings.speeddesk_mode == "paper"
    assert (settings.speeddesk_window_usd, settings.speeddesk_open_usd, settings.speeddesk_day_stop_usd) == (20, 20, 10)
    assert not settings.public_dict()["speeddesk_kalshi_live_confirmed"]
    assert settings.polydesk_mode == "paper" and settings.polydesk_live_contracts == 1
    assert settings.polydesk_live_max_open_usd == 10 and not settings.marco_real


@pytest.mark.parametrize("name,maximum", [
    ("speeddesk_kalshi_window_usd", 10), ("speeddesk_kalshi_open_usd", 20),
    ("speeddesk_kalshi_day_stop_usd", 6), ("speeddesk_kalshi_total_stop_usd", 10),
])
def test_kalshi_limits_cannot_exceed_authorized_ceiling_or_bypass_numeric_guards(name, maximum) -> None:
    assert getattr(Settings(**{name: maximum / 2}), name) == maximum / 2
    assert getattr(Settings.from_env({name.upper(): str(maximum)}), name) == maximum
    for value in (0, -1, maximum + 0.000001, float("inf"), float("nan"), True, "2"):
        with pytest.raises(ConfigError, match=name.upper()):
            Settings(**{name: value})
    with pytest.raises(ConfigError, match=name.upper()):
        Settings.from_env({name.upper(): str(maximum + 1)})


@pytest.mark.parametrize("cutoff", [0, 59.9, 900, float("nan"), float("inf"), False, "180"])
def test_kalshi_live_cutoff_cannot_enter_final_minute_or_disable_clock_guard(cutoff) -> None:
    with pytest.raises(ConfigError, match="SPEEDDESK_KALSHI_CUTOFF_S"):
        Settings(speeddesk_kalshi_cutoff_s=cutoff)


def test_missing_live_gates_do_not_stop_the_other_desks_at_configuration_time() -> None:
    # Runtime must enforce all four gates. Missing credentials/confirmation must pause only the companion,
    # not crash shared startup or prevent the owner switching either enable flag off.
    for values in (
        {"SPEEDDESK_KALSHI_MODE": "live"},
        {"SPEEDDESK_KALSHI_MODE": "live", "SPEEDDESK_KALSHI_LIVE_CONFIRM": "yes"},
        {"SPEEDDESK_KALSHI_MODE": "live", "SPEEDDESK_KALSHI_ENABLED": "false"},
        {"SPEEDDESK_KALSHI_MODE": "live", "SPEEDDESK_ENABLED": "false"},
    ):
        settings = Settings.from_env(values)
        assert settings.speeddesk_kalshi_mode == "live"
        assert settings.speeddesk_mode == "paper" and settings.polydesk_mode == "paper"
    with pytest.raises(ConfigError, match="SPEEDDESK_KALSHI_MODE"):
        Settings(speeddesk_kalshi_mode="automatic")
    with pytest.raises(ConfigError, match="SPEEDDESK_MODE"):
        Settings(speeddesk_mode="live")


@pytest.mark.parametrize("account_type", ["unknown", "direct", "fcm"])
def test_account_fee_category_is_public_factual_metadata_and_never_enables_trading(account_type: str) -> None:
    settings = Settings.from_env({"SPEEDDESK_KALSHI_ACCOUNT_TYPE": account_type})
    assert settings.speeddesk_kalshi_account_type == account_type
    assert settings.public_dict()["speeddesk_kalshi_account_type"] == account_type
    assert settings.speeddesk_kalshi_mode == "paper" and settings.speeddesk_kalshi_live_confirm is None
    assert settings.kalshi_key_id is None and settings.kalshi_private_key is None


@pytest.mark.parametrize("account_type", ["DIRECT", "broker", "yes", True, None])
def test_account_fee_category_requires_an_exact_supported_fact(account_type) -> None:
    with pytest.raises(ConfigError, match="SPEEDDESK_KALSHI_ACCOUNT_TYPE"):
        Settings(speeddesk_kalshi_account_type=account_type)


@pytest.mark.parametrize("source", ["environment", "direct", "replace"])
def test_kalshi_keys_resume_and_confirmation_are_secret_wrapped_everywhere(source) -> None:
    values = {"kalshi_key_id": "test-only-kalshi-key-id", "kalshi_private_key": "test-only-signing-material",
              "speeddesk_kalshi_resume_token": "test-only-resume-value",
              "speeddesk_kalshi_integrity_reset_token": "test-only-reset-value",
              "speeddesk_kalshi_live_confirm": "test-only-invalid-confirm"}
    if source == "environment":
        settings = Settings.from_env({name.upper(): value for name, value in values.items()})
    elif source == "direct":
        settings = Settings(**values)
    else:
        settings = Settings().replace(**values)
    for name in values:
        assert isinstance(getattr(settings, name), Secret)
    public = settings.public_dict()
    assert public["kalshi_key_id_set"] and public["kalshi_private_key_set"]
    assert public["speeddesk_kalshi_resume_token_set"]
    assert public["speeddesk_kalshi_integrity_reset_token_set"]
    assert not public["speeddesk_kalshi_live_confirmed"]
    for value in values.values():
        assert value not in repr(settings)
        assert value not in json.dumps(public)
        assert value not in str(getattr(settings, next(name for name, raw in values.items() if raw == value)))
        assert value in settings.secret_values()
        assert value not in redact_text(f"Provider echoed {value}", settings.secret_values())
    assert not set(values) & public.keys()


def test_exact_confirm_only_affects_public_confirmation_flag_never_default_mode() -> None:
    for value in ("YES", "true", "1", "on"):
        settings = Settings.from_env({"SPEEDDESK_KALSHI_LIVE_CONFIRM": value})
        assert not settings.public_dict()["speeddesk_kalshi_live_confirmed"]
        assert settings.speeddesk_kalshi_mode == "paper"
    confirmed = Settings.from_env({"SPEEDDESK_KALSHI_LIVE_CONFIRM": "yes"})
    assert confirmed.public_dict()["speeddesk_kalshi_live_confirmed"]
    assert confirmed.speeddesk_kalshi_mode == "paper"


def test_invalid_secret_types_are_rejected_without_echoing_values() -> None:
    for name in ("kalshi_key_id", "kalshi_private_key", "speeddesk_kalshi_resume_token",
                 "speeddesk_kalshi_integrity_reset_token", "speeddesk_kalshi_live_confirm"):
        with pytest.raises(ConfigError) as error:
            Settings(**{name: b"test-only-secret-bytes"})
        assert name.upper() in str(error.value)
        assert "test-only-secret-bytes" not in str(error.value)
