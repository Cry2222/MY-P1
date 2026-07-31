from __future__ import annotations

import pytest

from myp1.core.models import Exposure
from myp1.strategy.ema_cross import EmaCrossStrategy

from .conftest import make_candles, ramp


def test_abstains_before_warmup():
    strategy = EmaCrossStrategy(3, 8)
    assert strategy.evaluate(make_candles(ramp(5, 100, 1))) is None


def test_goes_long_in_a_rising_market():
    strategy = EmaCrossStrategy(3, 8)
    signal = strategy.evaluate(make_candles(ramp(40, 100, 1)))
    assert signal is not None
    assert signal.target is Exposure.LONG


def test_goes_flat_in_a_falling_market_when_long_only():
    strategy = EmaCrossStrategy(3, 8, long_only=True)
    signal = strategy.evaluate(make_candles(ramp(40, 200, -1)))
    assert signal is not None
    assert signal.target is Exposure.FLAT


def test_goes_short_in_a_falling_market_when_shorting_is_enabled():
    strategy = EmaCrossStrategy(3, 8, long_only=False)
    signal = strategy.evaluate(make_candles(ramp(40, 200, -1)))
    assert signal is not None
    assert signal.target is Exposure.SHORT


def test_reports_the_last_close_as_the_signal_price():
    candles = make_candles(ramp(40, 100, 1))
    signal = EmaCrossStrategy(3, 8).evaluate(candles)
    assert signal.price == pytest.approx(candles[-1].close)
    assert signal.symbol == candles[-1].symbol


def test_labels_the_bar_where_the_averages_cross():
    # Falling then sharply rising: somewhere in the rise the fast EMA crosses.
    closes = ramp(30, 200, -2) + ramp(30, 140, 4)
    reasons = []
    for end in range(20, len(closes)):
        signal = EmaCrossStrategy(3, 8).evaluate(make_candles(closes[:end]))
        if signal:
            reasons.append(signal.reason)
    assert any("crossover" in r for r in reasons)


def test_confidence_is_bounded():
    signal = EmaCrossStrategy(3, 8).evaluate(make_candles(ramp(60, 100, 5)))
    assert 0.0 <= signal.confidence <= 1.0


def test_rejects_inverted_periods():
    with pytest.raises(ValueError):
        EmaCrossStrategy(20, 10)
