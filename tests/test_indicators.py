from __future__ import annotations

import pytest

from myp1.strategy.indicators import atr, ema, sma


def test_sma_matches_manual_average():
    assert sma([1, 2, 3, 4, 5], 3) == pytest.approx([2.0, 3.0, 4.0])


def test_sma_returns_empty_when_too_short():
    assert sma([1, 2], 5) == []


def test_ema_seeds_on_the_simple_average():
    values = [1, 2, 3, 4, 5, 6]
    out = ema(values, 3)
    assert out[0] == pytest.approx(2.0)  # sma of 1,2,3
    assert len(out) == len(values) - 3 + 1


def test_ema_tracks_a_constant_series_exactly():
    assert ema([7.0] * 20, 5) == pytest.approx([7.0] * 16)


def test_ema_reacts_faster_than_sma_on_a_step():
    # One bar after the step, the EMA has moved further than the SMA. Given
    # enough bars the SMA catches up and passes it, so the window matters.
    values = [10.0] * 10 + [20.0]
    assert ema(values, 5)[-1] > sma(values, 5)[-1]


def test_sma_fully_absorbs_a_step_after_one_window():
    values = [10.0] * 10 + [20.0] * 5
    assert sma(values, 5)[-1] == pytest.approx(20.0)
    assert ema(values, 5)[-1] < 20.0  # EMA only approaches it


def test_ema_rejects_bad_period():
    with pytest.raises(ValueError):
        ema([1, 2, 3], 0)


def test_atr_is_positive_for_a_volatile_series():
    highs = [10, 12, 14, 13, 15, 16]
    lows = [8, 9, 11, 10, 12, 13]
    closes = [9, 11, 13, 11, 14, 15]
    out = atr(highs, lows, closes, 2)
    assert out and all(v > 0 for v in out)


def test_atr_rejects_mismatched_lengths():
    with pytest.raises(ValueError):
        atr([1, 2], [1], [1, 2], 2)
