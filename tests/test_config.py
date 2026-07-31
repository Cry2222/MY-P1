from __future__ import annotations

import pytest

from myp1.config import LIVE_CONFIRM_PHRASE, Config, ConfigError, load_config


def env(monkeypatch, **values):
    for key in list(values):
        monkeypatch.setenv(key, str(values[key]))


def test_defaults_to_paper_mode(monkeypatch):
    monkeypatch.delenv("MYP1_MODE", raising=False)
    assert load_config().mode == "paper"


def test_rejects_an_unknown_mode(monkeypatch):
    env(monkeypatch, MYP1_MODE="yolo")
    with pytest.raises(ConfigError, match="MYP1_MODE"):
        load_config()


def test_live_mode_requires_the_confirmation_phrase(monkeypatch):
    env(monkeypatch, MYP1_MODE="live", MYP1_API_KEY="k", MYP1_API_SECRET="s",
        MYP1_TELEGRAM_TOKEN="t", MYP1_TELEGRAM_OWNER_ID="1")
    monkeypatch.delenv("MYP1_LIVE_CONFIRM", raising=False)
    with pytest.raises(ConfigError, match="MYP1_LIVE_CONFIRM"):
        load_config()


def test_live_mode_requires_credentials(monkeypatch):
    env(monkeypatch, MYP1_MODE="live", MYP1_LIVE_CONFIRM=LIVE_CONFIRM_PHRASE,
        MYP1_TELEGRAM_TOKEN="t", MYP1_TELEGRAM_OWNER_ID="1")
    monkeypatch.delenv("MYP1_API_KEY", raising=False)
    monkeypatch.delenv("MYP1_API_SECRET", raising=False)
    with pytest.raises(ConfigError, match="MYP1_API_KEY"):
        load_config()


def test_live_mode_requires_a_reachable_kill_switch(monkeypatch):
    env(monkeypatch, MYP1_MODE="live", MYP1_LIVE_CONFIRM=LIVE_CONFIRM_PHRASE,
        MYP1_API_KEY="k", MYP1_API_SECRET="s")
    monkeypatch.delenv("MYP1_TELEGRAM_TOKEN", raising=False)
    monkeypatch.delenv("MYP1_TELEGRAM_OWNER_ID", raising=False)
    with pytest.raises(ConfigError, match="Telegram"):
        load_config()


def test_live_mode_accepts_a_fully_armed_config(monkeypatch):
    env(monkeypatch, MYP1_MODE="live", MYP1_LIVE_CONFIRM=LIVE_CONFIRM_PHRASE,
        MYP1_API_KEY="k", MYP1_API_SECRET="s",
        MYP1_TELEGRAM_TOKEN="t", MYP1_TELEGRAM_OWNER_ID="42")
    config = load_config()
    assert config.is_live
    assert config.telegram.usable


def test_paper_mode_needs_no_credentials(monkeypatch):
    for key in ("MYP1_MODE", "MYP1_API_KEY", "MYP1_API_SECRET", "MYP1_TELEGRAM_TOKEN"):
        monkeypatch.delenv(key, raising=False)
    config = load_config()
    assert not config.is_live
    assert config.api_key is None


def test_rejects_inverted_ema_periods(monkeypatch):
    env(monkeypatch, MYP1_FAST_PERIOD="50", MYP1_SLOW_PERIOD="10")
    with pytest.raises(ConfigError, match="FAST_PERIOD"):
        load_config()


def test_rejects_a_non_numeric_number(monkeypatch):
    env(monkeypatch, MYP1_RISK_FRACTION="lots")
    with pytest.raises(ConfigError, match="must be a number"):
        load_config()


def test_rejects_a_non_integer_owner_id(monkeypatch):
    env(monkeypatch, MYP1_TELEGRAM_OWNER_ID="not-a-number")
    with pytest.raises(ConfigError, match="OWNER_ID"):
        load_config()


def test_telegram_is_unusable_without_both_halves():
    from myp1.config import TelegramConfig

    assert not TelegramConfig(token="t").usable
    assert not TelegramConfig(owner_chat_id=1).usable
    assert not TelegramConfig(token="t", owner_chat_id=1, enabled=False).usable
    assert TelegramConfig(token="t", owner_chat_id=1).usable


def test_risk_limits_cannot_be_disabled():
    from myp1.config import RiskConfig

    with pytest.raises(ConfigError):
        Config(risk=RiskConfig(max_position_notional=0)).validate()
    with pytest.raises(ConfigError):
        Config(risk=RiskConfig(max_orders_per_day=0)).validate()
