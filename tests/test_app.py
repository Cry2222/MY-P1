"""Composition-root wiring.

The on-device install has neither FastAPI nor python-telegram-bot. These tests
pin the behaviour that makes that work: optional dependencies must be optional
at import time, not just in configuration.
"""

from __future__ import annotations

import builtins
import dataclasses

import pytest

from myp1.app import build_gateway, build_strategy, build_venue
from myp1.config import ApiConfig, Config, TelegramConfig
from myp1.execution.paper import PaperVenue
from myp1.marketdata.replay_source import ReplayMarketData
from myp1.risk.engine import RiskEngine
from myp1.runner import TradingRunner
from myp1.state.journal import Journal
from myp1.strategy.ema_cross import EmaCrossStrategy

from .conftest import make_candles, ramp


@pytest.fixture
def runner(config: Config):
    journal = Journal(config.journal_path)
    r = TradingRunner(
        config,
        market_data=ReplayMarketData(make_candles(ramp(60, 100, 2), config.symbol)),
        strategy=EmaCrossStrategy(config.fast_period, config.slow_period),
        risk=RiskEngine(config.risk),
        venue=PaperVenue(config.starting_cash),
        journal=journal,
    )
    yield r
    journal.close()


def test_no_gateway_when_telegram_is_unconfigured(config, runner):
    assert build_gateway(config, runner) is None


def test_missing_telegram_package_does_not_stop_the_bot(config, runner, monkeypatch):
    """Termux often cannot install python-telegram-bot. That must not be fatal."""
    configured = dataclasses.replace(
        config, telegram=TelegramConfig(token="123:FAKE", owner_chat_id=42)
    )
    assert configured.telegram.usable

    real_import = builtins.__import__

    def deny_telegram(name, *args, **kwargs):
        if name.startswith("telegram") or "telegram_bot" in name:
            raise ImportError("No module named 'telegram'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", deny_telegram)
    # Returns None rather than raising — the bot starts without alerts.
    assert build_gateway(configured, runner) is None


def test_gateway_is_built_when_available(config, runner):
    configured = dataclasses.replace(
        config, telegram=TelegramConfig(token="123:FAKE", owner_chat_id=42)
    )
    gateway = build_gateway(configured, runner)
    assert gateway is not None
    assert callable(gateway.send)


def test_paper_venue_is_the_default(config):
    venue = build_venue(config)
    assert isinstance(venue, PaperVenue)
    assert venue.is_live is False


def test_shorting_config_enables_it_on_the_paper_venue(config):
    venue = build_venue(dataclasses.replace(config, long_only=False))
    assert isinstance(venue, PaperVenue)
    assert venue.allow_short is True


def test_unknown_strategy_is_rejected(config):
    with pytest.raises(ValueError, match="Unknown strategy"):
        build_strategy(dataclasses.replace(config, strategy="not-a-strategy"))


def test_api_alone_satisfies_the_live_kill_switch_requirement(config):
    """An on-device install has no Telegram; the app is the kill switch."""
    on_device = dataclasses.replace(
        config,
        telegram=TelegramConfig(enabled=False),
        api=ApiConfig(enabled=True, token="a-token-that-is-long-enough-123", server="lite"),
    )
    assert on_device.has_remote_stop is True
