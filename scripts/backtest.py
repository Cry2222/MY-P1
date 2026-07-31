#!/usr/bin/env python3
"""Replay candles through the real trading pipeline.

This is not a separate simulator. It swaps the market-data seam for a replay
source and the execution seam for the paper venue, and runs the identical
runner, strategy and risk engine that live mode uses. A result here means the
same code path behaved that way — which is the whole point of the seams.

    python scripts/backtest.py --csv data/btc-1m.csv --symbol BTC/USDT
    python scripts/backtest.py --synthetic 500

CSV columns: timestamp,open,high,low,close,volume
"""

from __future__ import annotations

import argparse
import asyncio
import math
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from myp1.config import Config, RiskConfig  # noqa: E402
from myp1.core.models import Candle  # noqa: E402
from myp1.execution.paper import PaperVenue  # noqa: E402
from myp1.marketdata.replay_source import ReplayMarketData  # noqa: E402
from myp1.risk.engine import RiskEngine  # noqa: E402
from myp1.runner import TradingRunner  # noqa: E402
from myp1.state.journal import Journal  # noqa: E402
from myp1.strategy.ema_cross import EmaCrossStrategy  # noqa: E402


def synthetic(n: int, symbol: str) -> list[Candle]:
    """A trending series with cycles and noise — enough to trigger crossings."""
    candles = []
    price = 100.0
    for i in range(n):
        drift = 0.03
        cycle = 3.0 * math.sin(2 * math.pi * i / 90)
        noise = 0.6 * math.sin(i * 2.399963)  # deterministic pseudo-noise
        price = max(1.0, 100.0 + drift * i + cycle + noise)
        candles.append(
            Candle(symbol, i * 60_000, price, price * 1.002, price * 0.998, price, 1.0)
        )
    return candles


async def main() -> int:
    parser = argparse.ArgumentParser(description="Replay a candle series through MY-P1")
    parser.add_argument("--csv", help="CSV of candles to replay")
    parser.add_argument("--synthetic", type=int, metavar="N",
                        help="generate N synthetic candles instead")
    parser.add_argument("--symbol", default="BTC/USDT")
    parser.add_argument("--fast", type=int, default=12)
    parser.add_argument("--slow", type=int, default=26)
    parser.add_argument("--cash", type=float, default=1000.0)
    parser.add_argument("--fee-pct", type=float, default=0.1)
    parser.add_argument("--slippage-pct", type=float, default=0.02)
    parser.add_argument("--max-notional", type=float, default=200.0)
    parser.add_argument("--risk-fraction", type=float, default=0.2)
    parser.add_argument("--max-daily-loss", type=float, default=1e9,
                        help="disabled by default so a backtest runs to the end")
    parser.add_argument("--max-orders", type=int, default=100_000)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    if not args.csv and not args.synthetic:
        parser.error("pass --csv PATH or --synthetic N")

    if args.csv:
        source = ReplayMarketData.from_csv(args.csv, args.symbol, warmup=args.slow + 2)
        total = len(source._candles)  # noqa: SLF001 - reporting only
    else:
        candles = synthetic(args.synthetic, args.symbol)
        source = ReplayMarketData(candles, warmup=args.slow + 2)
        total = len(candles)

    config = Config(
        mode="paper",
        symbol=args.symbol,
        poll_seconds=0.0001,
        starting_cash=args.cash,
        fee_pct=args.fee_pct,
        slippage_pct=args.slippage_pct,
        fast_period=args.fast,
        slow_period=args.slow,
        journal_path=str(Path(tempfile.mkdtemp()) / "backtest.sqlite3"),
        risk=RiskConfig(
            max_position_notional=args.max_notional,
            risk_fraction=args.risk_fraction,
            max_daily_loss=args.max_daily_loss,
            max_orders_per_day=args.max_orders,
            max_slippage_pct=100.0,   # slippage is simulated, not a live surprise
            min_order_notional=1.0,
        ),
    )
    config.validate()

    venue = PaperVenue(args.cash, fee_pct=args.fee_pct,
                       slippage_pct=args.slippage_pct)
    journal = Journal(config.journal_path)
    runner = TradingRunner(
        config,
        market_data=source,
        strategy=EmaCrossStrategy(args.fast, args.slow, long_only=config.long_only),
        risk=RiskEngine(config.risk),
        venue=venue,
        journal=journal,
    )

    trades = 0
    while not source.exhausted:
        result = await runner.tick()
        if result.fill:
            trades += 1
            if args.verbose:
                print(f"  {result.fill.side.value:4} {result.fill.quantity:.6f} "
                      f"@ {result.fill.price:.2f}")

    mark = runner.last_price
    equity = await venue.equity(mark)
    status = runner.status()
    buy_hold = args.cash * (mark / synthetic_first(source)) if mark else args.cash

    print(f"\n{'=' * 52}")
    print(f"  candles replayed   {total}")
    print(f"  strategy           {runner.strategy.name}")
    print(f"  trades             {trades}")
    print(f"  realized PnL       {status['realized_total']:+.2f}")
    print(f"  unrealized PnL     {status['unrealized']:+.2f}")
    print(f"  final equity       {equity:.2f}  (started {args.cash:.2f})")
    print(f"  return             {(equity / args.cash - 1) * 100:+.2f}%")
    print(f"  buy & hold         {(buy_hold / args.cash - 1) * 100:+.2f}%")
    print(f"  open position      {status['position_side']} {status['position_qty']:.6f}")
    print(f"{'=' * 52}\n")

    journal.close()
    return 0


def synthetic_first(source: ReplayMarketData) -> float:
    return source._candles[0].close  # noqa: SLF001 - reporting only


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
