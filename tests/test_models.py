from __future__ import annotations

import pytest

from myp1.core.models import Exposure, Fill, Position, Side


def fill(side: Side, qty: float, price: float, fee: float = 0.0) -> Fill:
    return Fill(
        symbol="TEST/USDT", side=side, quantity=qty, price=price,
        fee=fee, timestamp=0, venue="test",
    )


def test_opening_a_long_sets_average_price():
    p = Position("TEST/USDT")
    p.apply(fill(Side.BUY, 2.0, 100.0))
    assert p.quantity == pytest.approx(2.0)
    assert p.avg_price == pytest.approx(100.0)
    assert p.exposure is Exposure.LONG


def test_adding_to_a_long_averages_the_entry():
    p = Position("TEST/USDT")
    p.apply(fill(Side.BUY, 1.0, 100.0))
    p.apply(fill(Side.BUY, 1.0, 200.0))
    assert p.avg_price == pytest.approx(150.0)
    assert p.quantity == pytest.approx(2.0)


def test_closing_a_long_realizes_the_gain():
    p = Position("TEST/USDT")
    p.apply(fill(Side.BUY, 2.0, 100.0))
    realized = p.apply(fill(Side.SELL, 2.0, 110.0))
    assert realized == pytest.approx(20.0)
    assert p.is_flat
    assert p.avg_price == 0.0


def test_fees_reduce_realized_pnl():
    p = Position("TEST/USDT")
    p.apply(fill(Side.BUY, 1.0, 100.0, fee=0.5))
    realized = p.apply(fill(Side.SELL, 1.0, 110.0, fee=0.5))
    assert realized == pytest.approx(9.5)
    assert p.realized_pnl == pytest.approx(9.0)  # both fees counted


def test_partial_close_keeps_the_remainder_at_entry_price():
    p = Position("TEST/USDT")
    p.apply(fill(Side.BUY, 4.0, 100.0))
    realized = p.apply(fill(Side.SELL, 1.0, 120.0))
    assert realized == pytest.approx(20.0)
    assert p.quantity == pytest.approx(3.0)
    assert p.avg_price == pytest.approx(100.0)


def test_short_position_profits_when_price_falls():
    p = Position("TEST/USDT")
    p.apply(fill(Side.SELL, 2.0, 100.0))
    assert p.exposure is Exposure.SHORT
    realized = p.apply(fill(Side.BUY, 2.0, 90.0))
    assert realized == pytest.approx(20.0)


def test_flipping_through_zero_reprices_the_new_side():
    p = Position("TEST/USDT")
    p.apply(fill(Side.BUY, 1.0, 100.0))
    realized = p.apply(fill(Side.SELL, 3.0, 110.0))
    assert realized == pytest.approx(10.0)      # only the 1.0 that closed
    assert p.quantity == pytest.approx(-2.0)
    assert p.avg_price == pytest.approx(110.0)  # remainder opened here


def test_unrealized_pnl_marks_against_current_price():
    p = Position("TEST/USDT")
    p.apply(fill(Side.BUY, 2.0, 100.0))
    assert p.unrealized_pnl(105.0) == pytest.approx(10.0)
    assert p.unrealized_pnl(95.0) == pytest.approx(-10.0)


def test_flat_position_has_no_unrealized_pnl():
    assert Position("TEST/USDT").unrealized_pnl(1234.0) == 0.0
