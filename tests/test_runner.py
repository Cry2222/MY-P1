"""End-to-end coverage of the trading loop, with no network and no exchange.

The replay market-data source plus the paper venue mean the whole pipeline —
signal, risk, execution, journal, notification — runs exactly as it would in
production, deterministically.
"""

from __future__ import annotations

import pytest

from myp1.core.models import Exposure, Side
from myp1.execution.base import ExecutionError
from myp1.execution.paper import PaperVenue
from myp1.marketdata.replay_source import ReplayMarketData
from myp1.risk.engine import RiskEngine
from myp1.runner import TradingRunner
from myp1.state.journal import Journal, today
from myp1.strategy.ema_cross import EmaCrossStrategy

from .conftest import make_candles, ramp


def build(config, closes, *, warmup=20, venue=None, notes=None):
    journal = Journal(config.journal_path)
    runner = TradingRunner(
        config,
        market_data=ReplayMarketData(make_candles(closes, config.symbol), warmup=warmup),
        strategy=EmaCrossStrategy(config.fast_period, config.slow_period,
                                  long_only=config.long_only),
        risk=RiskEngine(config.risk),
        venue=venue or PaperVenue(config.starting_cash, fee_pct=config.fee_pct,
                                  slippage_pct=config.slippage_pct),
        journal=journal,
        notifier=(lambda text: _collect(notes, text)) if notes is not None else None,
    )
    return runner, journal


async def _collect(sink: list[str], text: str) -> None:
    sink.append(text)


@pytest.mark.asyncio
async def test_rising_market_opens_a_long(config):
    runner, journal = build(config, ramp(60, 100, 2))
    for _ in range(10):
        result = await runner.tick()
        if result.fill:
            break
    assert runner.position.exposure is Exposure.LONG
    assert journal.fill_count() == 1
    journal.close()


@pytest.mark.asyncio
async def test_reversal_exits_before_it_re_enters(config):
    # Rise to open a long, then a sharp fall to force the exit.
    runner, journal = build(config, ramp(40, 100, 3) + ramp(40, 220, -6))
    fills = []
    for _ in range(70):
        result = await runner.tick()
        if result.fill:
            fills.append(result.fill)

    assert len(fills) >= 2
    assert fills[0].side is Side.BUY
    assert fills[1].side is Side.SELL
    # A single order never crosses through zero.
    assert fills[1].quantity == pytest.approx(fills[0].quantity)
    journal.close()


@pytest.mark.asyncio
async def test_holding_the_target_places_no_order(config):
    runner, journal = build(config, ramp(60, 100, 2))
    for _ in range(10):
        if (await runner.tick()).fill:
            break
    before = journal.fill_count()

    result = await runner.tick()
    assert result.order is None
    assert "already held" in result.note
    assert journal.fill_count() == before
    journal.close()


@pytest.mark.asyncio
async def test_kill_switch_stops_all_trading(config):
    runner, journal = build(config, ramp(60, 100, 2))
    runner.kill("test")

    for _ in range(10):
        result = await runner.tick()
        assert result.fill is None
    assert runner.position.is_flat
    assert journal.fill_count() == 0
    journal.close()


@pytest.mark.asyncio
async def test_kill_switch_persists_across_a_restart(config):
    runner, journal = build(config, ramp(60, 100, 2))
    runner.kill("test")
    journal.close()

    runner2, journal2 = build(config, ramp(60, 100, 2))
    assert runner2.killed is True
    journal2.close()


@pytest.mark.asyncio
async def test_pause_blocks_entry_then_resume_allows_it(config):
    runner, journal = build(config, ramp(60, 100, 2))
    runner.pause()
    for _ in range(6):
        result = await runner.tick()
        assert result.fill is None
        if result.rejected:
            assert "paused" in result.rejected

    runner.resume()
    filled = False
    for _ in range(10):
        if (await runner.tick()).fill:
            filled = True
            break
    assert filled
    journal.close()


@pytest.mark.asyncio
async def test_daily_loss_limit_stops_new_entries(config):
    import dataclasses
    import time

    from myp1.core.models import Fill

    tight = dataclasses.replace(
        config, risk=dataclasses.replace(config.risk, max_daily_loss=10.0)
    )
    runner, journal = build(tight, ramp(60, 100, 2))

    # Book a loss today so the limit is already breached before the first tick.
    journal.record_fill(
        Fill(tight.symbol, Side.SELL, 1.0, 100.0, 0.0, int(time.time() * 1000), "paper"),
        realized=-50.0,
    )
    assert journal.realized_pnl(today()) == pytest.approx(-50.0)

    for _ in range(10):
        result = await runner.tick()
        assert result.fill is None, "traded past the daily loss limit"
        if result.rejected:
            assert "daily loss limit" in result.rejected
    journal.close()


@pytest.mark.asyncio
async def test_position_is_recovered_from_the_journal_on_restart(config):
    runner, journal = build(config, ramp(60, 100, 2))
    for _ in range(10):
        if (await runner.tick()).fill:
            break
    quantity = runner.position.quantity
    assert quantity > 0
    journal.close()

    runner2, journal2 = build(config, ramp(60, 100, 2))
    assert runner2.position.quantity == pytest.approx(quantity)
    assert runner2.venue.inventory(config.symbol) == pytest.approx(quantity)
    journal2.close()


@pytest.mark.asyncio
async def test_execution_failure_is_recorded_and_does_not_crash(config):
    class BrokenVenue(PaperVenue):
        async def submit(self, order):
            raise ExecutionError("exchange unreachable")

    notes: list[str] = []
    runner, journal = build(config, ramp(60, 100, 2),
                            venue=BrokenVenue(config.starting_cash), notes=notes)

    saw_failure = False
    for _ in range(10):
        result = await runner.tick()
        if result.rejected == "exchange unreachable":
            saw_failure = True
            break

    assert saw_failure
    assert runner.errors >= 1
    assert any("Order failed" in n for n in notes)
    journal.close()


@pytest.mark.asyncio
async def test_slippage_breach_engages_the_kill_switch(config):
    notes: list[str] = []
    # 5% simulated slippage against a 0.5% tolerance.
    venue = PaperVenue(config.starting_cash, fee_pct=0.0, slippage_pct=5.0)
    runner, journal = build(config, ramp(60, 100, 2), venue=venue, notes=notes)

    for _ in range(10):
        result = await runner.tick()
        if result.fill:
            break

    assert runner.killed is True
    assert any("Kill switch" in n for n in notes)
    # The fill that breached is still journalled — it really happened.
    assert journal.fill_count() == 1
    journal.close()


@pytest.mark.asyncio
async def test_notifier_failure_never_breaks_the_loop(config):
    async def exploding(_text: str) -> None:
        raise RuntimeError("telegram down")

    runner, journal = build(config, ramp(60, 100, 2))
    runner.notifier = exploding

    for _ in range(10):
        result = await runner.tick()
        if result.fill:
            break
    assert runner.position.exposure is Exposure.LONG  # trade still went through
    journal.close()


@pytest.mark.asyncio
async def test_run_loop_honours_max_ticks_and_stop(config):
    runner, journal = build(config, ramp(60, 100, 2))
    await runner.run(max_ticks=3)
    assert runner.ticks == 3
    assert runner.status()["running"] is False
    journal.close()


@pytest.mark.asyncio
async def test_status_reports_the_live_picture(config):
    runner, journal = build(config, ramp(60, 100, 2))
    for _ in range(10):
        if (await runner.tick()).fill:
            break

    status = runner.status()
    assert status["mode"] == "paper"
    assert status["symbol"] == config.symbol
    assert status["position_side"] == "long"
    assert status["last_price"] > 0
    assert status["orders_today"] >= 1
    journal.close()
