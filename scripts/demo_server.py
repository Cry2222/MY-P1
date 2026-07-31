#!/usr/bin/env python3
"""Run the real bot and its real API against replayed candles.

Useful for developing the mobile app without an exchange, and for seeing the
whole system work end to end offline. Everything is genuine except the price
feed and the fills: same runner, same risk engine, same API.

    python scripts/demo_server.py --port 8333 --token dev-token-at-least-24-chars

Then point the mobile app at http://127.0.0.1:8333
"""

from __future__ import annotations

import argparse
import asyncio
import math
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from myp1.api.server import create_app, serve  # noqa: E402
from myp1.config import ApiConfig, Config  # noqa: E402
from myp1.core.models import Candle  # noqa: E402
from myp1.execution.paper import PaperVenue  # noqa: E402
from myp1.marketdata.replay_source import ReplayMarketData  # noqa: E402
from myp1.risk.engine import RiskEngine  # noqa: E402
from myp1.runner import TradingRunner  # noqa: E402
from myp1.state.journal import Journal  # noqa: E402
from myp1.strategy.ema_cross import EmaCrossStrategy  # noqa: E402

DEFAULT_TOKEN = "dev-token-at-least-24-characters-long"


def series(n: int, symbol: str) -> list[Candle]:
    out = []
    for i in range(n):
        price = (
            30000
            + 40 * i
            + 900 * math.sin(2 * math.pi * i / 120)
            + 180 * math.sin(i * 2.399963)
        )
        out.append(
            Candle(symbol, 1_700_000_000_000 + i * 60_000, price,
                   price * 1.003, price * 0.997, price, 12.5)
        )
    return out


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8333)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--token", default=DEFAULT_TOKEN)
    parser.add_argument("--symbol", default="BTC/USDT")
    parser.add_argument("--warm-ticks", type=int, default=140,
                        help="ticks to run before serving, so there is history")
    parser.add_argument("--cors", default="*",
                        help="comma-separated origins for the web preview")
    args = parser.parse_args()

    config = Config(
        mode="paper",
        symbol=args.symbol,
        poll_seconds=2.0,
        starting_cash=5000.0,
        fast_period=5,
        slow_period=20,
        journal_path=str(Path(tempfile.mkdtemp()) / "demo.sqlite3"),
    )
    config.validate()

    source = ReplayMarketData(series(600, args.symbol), warmup=25)
    journal = Journal(config.journal_path)
    runner = TradingRunner(
        config,
        market_data=source,
        strategy=EmaCrossStrategy(config.fast_period, config.slow_period),
        risk=RiskEngine(config.risk),
        venue=PaperVenue(config.starting_cash, fee_pct=0.1, slippage_pct=0.02),
        journal=journal,
    )

    print(f"warming up {args.warm_ticks} ticks…")
    for _ in range(args.warm_ticks):
        await runner.tick()
    print(f"  fills so far: {journal.fill_count()}")
    print(f"  realized PnL: {journal.realized_pnl():+.2f}")

    api_config = ApiConfig(
        enabled=True,
        host=args.host,
        port=args.port,
        token=args.token,
        docs_enabled=True,
        cors_origins=tuple(o.strip() for o in args.cors.split(",") if o.strip()),
    )
    app = create_app(runner, api_config)

    print(f"\n  API   http://{args.host}:{args.port}")
    print(f"  docs  http://{args.host}:{args.port}/api/docs")
    print(f"  token {args.token}\n")

    await asyncio.gather(runner.run(), serve(app, args.host, args.port))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
