from __future__ import annotations

import pytest

from myp1.core.models import Exposure, Fill, Order, Side
from myp1.state.journal import Journal, today


@pytest.fixture
def journal(tmp_path) -> Journal:
    j = Journal(tmp_path / "j.sqlite3")
    yield j
    j.close()


def fill(side: Side, qty: float, price: float, fee: float = 0.0) -> Fill:
    return Fill("TEST/USDT", side, qty, price, fee, 1_700_000_000_000, "paper")


def test_position_rebuilds_from_recorded_fills(journal):
    journal.record_fill(fill(Side.BUY, 2.0, 100.0), 0.0)
    journal.record_fill(fill(Side.SELL, 1.0, 110.0), 10.0)

    position = journal.rebuild_position("TEST/USDT")
    assert position.quantity == pytest.approx(1.0)
    assert position.avg_price == pytest.approx(100.0)
    assert position.exposure is Exposure.LONG


def test_position_survives_a_restart(tmp_path):
    path = tmp_path / "restart.sqlite3"
    first = Journal(path)
    first.record_fill(fill(Side.BUY, 3.0, 50.0), 0.0)
    first.close()

    second = Journal(path)
    assert second.rebuild_position("TEST/USDT").quantity == pytest.approx(3.0)
    second.close()


def test_realized_pnl_sums_only_the_requested_day(journal):
    journal.record_fill(fill(Side.SELL, 1.0, 110.0), 10.0)
    assert journal.realized_pnl() == pytest.approx(10.0)
    assert journal.realized_pnl("1999-01-01") == pytest.approx(0.0)


def test_only_filled_orders_count_toward_the_daily_cap(journal):
    order = Order("TEST/USDT", Side.BUY, 1.0, 100.0)
    journal.record_order(order, "filled")
    journal.record_order(order, "rejected", "risk said no")
    assert journal.order_count(today()) == 1


def test_control_flags_round_trip(journal):
    assert journal.get_control("kill_switch", False) is False
    journal.set_control("kill_switch", True)
    assert journal.get_control("kill_switch") is True
    journal.set_control("kill_switch", False)
    assert journal.get_control("kill_switch") is False


def test_recent_fills_are_newest_first(journal):
    journal.record_fill(fill(Side.BUY, 1.0, 100.0), 0.0)
    journal.record_fill(fill(Side.SELL, 1.0, 120.0), 20.0)
    rows = journal.recent_fills(limit=2)
    assert rows[0]["side"] == "sell"
    assert journal.fill_count() == 2
