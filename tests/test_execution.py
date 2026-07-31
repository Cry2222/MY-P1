from __future__ import annotations

import pytest

from myp1.core.models import Order, Side
from myp1.execution.base import ExecutionError
from myp1.execution.paper import PaperVenue


def order(side: Side, qty: float, price: float = 100.0) -> Order:
    return Order(symbol="TEST/USDT", side=side, quantity=qty, price=price)


@pytest.mark.asyncio
async def test_buy_debits_cash_and_credits_inventory():
    venue = PaperVenue(1000.0, fee_pct=0.0, slippage_pct=0.0)
    fill = await venue.submit(order(Side.BUY, 2.0))
    assert fill.price == pytest.approx(100.0)
    assert venue.cash == pytest.approx(800.0)
    assert venue.inventory("TEST/USDT") == pytest.approx(2.0)


@pytest.mark.asyncio
async def test_slippage_always_works_against_the_order():
    venue = PaperVenue(1000.0, fee_pct=0.0, slippage_pct=1.0)
    buy = await venue.submit(order(Side.BUY, 1.0))
    assert buy.price == pytest.approx(101.0)

    sell = await venue.submit(order(Side.SELL, 1.0))
    assert sell.price == pytest.approx(99.0)


@pytest.mark.asyncio
async def test_fees_are_charged_on_both_sides():
    venue = PaperVenue(1000.0, fee_pct=1.0, slippage_pct=0.0)
    buy = await venue.submit(order(Side.BUY, 1.0))
    assert buy.fee == pytest.approx(1.0)
    assert venue.cash == pytest.approx(899.0)


@pytest.mark.asyncio
async def test_cannot_spend_more_cash_than_the_account_holds():
    venue = PaperVenue(50.0)
    with pytest.raises(ExecutionError, match="insufficient paper cash"):
        await venue.submit(order(Side.BUY, 10.0))


@pytest.mark.asyncio
async def test_cannot_sell_what_is_not_held_when_shorting_is_off():
    venue = PaperVenue(1000.0)
    with pytest.raises(ExecutionError, match="insufficient paper inventory"):
        await venue.submit(order(Side.SELL, 1.0))


@pytest.mark.asyncio
async def test_short_selling_is_allowed_when_enabled():
    venue = PaperVenue(1000.0, fee_pct=0.0, slippage_pct=0.0, allow_short=True)
    await venue.submit(order(Side.SELL, 1.0))
    assert venue.inventory("TEST/USDT") == pytest.approx(-1.0)


@pytest.mark.asyncio
async def test_rejects_non_positive_quantity():
    venue = PaperVenue(1000.0)
    with pytest.raises(ExecutionError):
        await venue.submit(order(Side.BUY, 0.0))


@pytest.mark.asyncio
async def test_equity_marks_inventory_at_the_current_price():
    venue = PaperVenue(1000.0, fee_pct=0.0, slippage_pct=0.0)
    await venue.submit(order(Side.BUY, 5.0))
    assert await venue.equity(100.0) == pytest.approx(1000.0)
    assert await venue.equity(120.0) == pytest.approx(1100.0)


@pytest.mark.asyncio
async def test_round_trip_at_a_higher_price_grows_cash():
    venue = PaperVenue(1000.0, fee_pct=0.0, slippage_pct=0.0)
    await venue.submit(order(Side.BUY, 1.0, price=100.0))
    await venue.submit(order(Side.SELL, 1.0, price=110.0))
    assert venue.cash == pytest.approx(1010.0)
    assert venue.inventory("TEST/USDT") == pytest.approx(0.0)


def test_live_venue_refuses_to_build_unarmed():
    from myp1.execution.live import LiveVenue

    with pytest.raises(ExecutionError, match="armed=True"):
        LiveVenue("binance", "key", "secret")


def test_live_venue_refuses_empty_credentials():
    from myp1.execution.live import LiveVenue

    with pytest.raises(ExecutionError, match="api_key and api_secret"):
        LiveVenue("binance", "", "", armed=True)
