from __future__ import annotations

import math

import pytest

from myp1.config import Config, RiskConfig
from myp1.core.models import Candle


def make_candles(closes: list[float], symbol: str = "TEST/USDT", start: int = 0) -> list[Candle]:
    """Build a candle series from close prices, one minute apart."""
    return [
        Candle(
            symbol=symbol,
            timestamp=start + i * 60_000,
            open=close,
            high=close * 1.001,
            low=close * 0.999,
            close=close,
            volume=1.0,
        )
        for i, close in enumerate(closes)
    ]


def ramp(n: int, start: float, step: float) -> list[float]:
    return [start + i * step for i in range(n)]


def wave(n: int, base: float = 100.0, amplitude: float = 10.0, period: int = 40) -> list[float]:
    return [base + amplitude * math.sin(2 * math.pi * i / period) for i in range(n)]


@pytest.fixture
def risk_config() -> RiskConfig:
    return RiskConfig(
        max_position_notional=100.0,
        risk_fraction=0.10,
        max_daily_loss=25.0,
        max_orders_per_day=40,
        max_slippage_pct=0.5,
        min_order_notional=5.0,
    )


@pytest.fixture
def config(tmp_path, risk_config) -> Config:
    return Config(
        mode="paper",
        symbol="TEST/USDT",
        timeframe="1m",
        poll_seconds=0.001,
        starting_cash=1000.0,
        fee_pct=0.1,
        slippage_pct=0.02,
        fast_period=3,
        slow_period=8,
        journal_path=str(tmp_path / "journal.sqlite3"),
        risk=risk_config,
    )
