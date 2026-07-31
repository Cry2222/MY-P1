from __future__ import annotations

import pytest

from myp1.config import ConfigError, RiskConfig
from myp1.core.models import Exposure, Fill, Position, Side, Signal
from myp1.risk.engine import RiskEngine, RiskState


def signal(target: Exposure = Exposure.LONG, price: float = 100.0) -> Signal:
    return Signal(symbol="TEST/USDT", target=target, price=price, timestamp=0)


def state(**kwargs) -> RiskState:
    base = dict(equity=1000.0, realized_pnl_today=0.0, orders_today=0)
    base.update(kwargs)
    return RiskState(**base)


def long_position(qty: float = 1.0, price: float = 100.0) -> Position:
    p = Position("TEST/USDT")
    p.apply(Fill("TEST/USDT", Side.BUY, qty, price, 0.0, 0, "test"))
    return p


def test_approves_a_clean_entry(risk_config):
    decision = RiskEngine(risk_config).assess(signal(), Position("TEST/USDT"), state())
    assert decision.approved
    assert decision.quantity == pytest.approx(1.0)  # 10% of 1000 equity / price 100


def test_position_size_is_capped_by_max_notional(risk_config):
    engine = RiskEngine(risk_config)
    decision = engine.assess(signal(), Position("TEST/USDT"), state(equity=100_000.0))
    assert decision.quantity * 100.0 == pytest.approx(risk_config.max_position_notional)


def test_kill_switch_blocks_entries(risk_config):
    decision = RiskEngine(risk_config).assess(
        signal(), Position("TEST/USDT"), state(killed=True)
    )
    assert not decision.approved
    assert "kill switch" in decision.reason


def test_kill_switch_also_blocks_exits(risk_config):
    # A kill switch that let exits through would not be a full stop.
    decision = RiskEngine(risk_config).assess(
        signal(Exposure.FLAT), long_position(), state(killed=True), is_exit=True
    )
    assert not decision.approved


def test_pause_blocks_entries_but_not_exits(risk_config):
    engine = RiskEngine(risk_config)
    assert not engine.assess(signal(), Position("TEST/USDT"), state(paused=True)).approved

    exit_decision = engine.assess(
        signal(Exposure.FLAT), long_position(), state(paused=True), is_exit=True
    )
    assert exit_decision.approved
    assert exit_decision.quantity == pytest.approx(1.0)


def test_daily_loss_limit_halts_new_entries(risk_config):
    decision = RiskEngine(risk_config).assess(
        signal(), Position("TEST/USDT"), state(realized_pnl_today=-25.0)
    )
    assert not decision.approved
    assert "daily loss limit" in decision.reason


def test_daily_loss_limit_still_allows_exit(risk_config):
    decision = RiskEngine(risk_config).assess(
        signal(Exposure.FLAT), long_position(),
        state(realized_pnl_today=-100.0), is_exit=True,
    )
    assert decision.approved


def test_daily_order_cap_stops_a_runaway_loop(risk_config):
    decision = RiskEngine(risk_config).assess(
        signal(), Position("TEST/USDT"), state(orders_today=40)
    )
    assert not decision.approved
    assert "order cap" in decision.reason


def test_does_not_stack_a_second_position(risk_config):
    decision = RiskEngine(risk_config).assess(signal(), long_position(), state())
    assert not decision.approved
    assert "already open" in decision.reason


def test_rejects_dust_orders(risk_config):
    decision = RiskEngine(risk_config).assess(
        signal(), Position("TEST/USDT"), state(equity=10.0)
    )
    assert not decision.approved
    assert "too small" in decision.reason


def test_rejects_when_equity_lookup_failed(risk_config):
    # The runner passes equity=0.0 when it cannot read the balance.
    decision = RiskEngine(risk_config).assess(
        signal(), Position("TEST/USDT"), state(equity=0.0)
    )
    assert not decision.approved


def test_rejects_invalid_price(risk_config):
    decision = RiskEngine(risk_config).assess(
        signal(price=0.0), Position("TEST/USDT"), state()
    )
    assert not decision.approved


def test_exit_on_a_flat_book_is_refused(risk_config):
    decision = RiskEngine(risk_config).assess(
        signal(Exposure.FLAT), Position("TEST/USDT"), state(), is_exit=True
    )
    assert not decision.approved
    assert "already flat" in decision.reason


def test_flat_target_is_not_an_entry(risk_config):
    decision = RiskEngine(risk_config).assess(
        signal(Exposure.FLAT), Position("TEST/USDT"), state()
    )
    assert not decision.approved


def test_slippage_within_tolerance_passes(risk_config):
    assert RiskEngine(risk_config).check_slippage(100.0, 100.2).approved


def test_slippage_beyond_tolerance_is_flagged(risk_config):
    decision = RiskEngine(risk_config).check_slippage(100.0, 101.0)
    assert not decision.approved
    assert "slippage" in decision.reason


def test_engine_refuses_an_unlimited_config():
    with pytest.raises(ConfigError):
        RiskEngine(RiskConfig(max_daily_loss=0.0))
    with pytest.raises(ConfigError):
        RiskEngine(RiskConfig(risk_fraction=1.5))
