# MY-P1

Auto-trading bot with a Telegram control surface, built as independent
components behind replaceable seams — the architecture pattern from
[Acme Software Factory](https://github.com/eimg/acme-software-factory).

MY-P1 is a **target application** in the Acme sense: the thing the factory
builds, not part of the factory. See [`docs/acme-setup.md`](docs/acme-setup.md)
for running the suite and pointing Helix at this repository.

## What it does

Polls an exchange for candles, runs a strategy, sizes the trade through a risk
engine, executes it on a venue, journals it, and reports to Telegram. The loop
runs unattended; Telegram is how you watch it and how you stop it.

```
market data ─→ strategy ─→ position diff ─→ risk ─→ execution ─→ journal ─→ telegram
```

Each arrow is a seam. Every component behind one is swappable without touching
its neighbours, which is what makes "run the same strategy against a simulator
first" a config change rather than a rewrite.

| Component | Package | Replaceable with |
|---|---|---|
| Market data | `myp1/marketdata` | any exchange via ccxt, CSV replay, a test fixture |
| Strategy | `myp1/strategy` | anything implementing `evaluate(candles) -> Signal` |
| Risk | `myp1/risk` | your own limits; the seam itself is mandatory |
| Execution | `myp1/execution` | paper simulator or live exchange |
| Journal | `myp1/state` | SQLite today; the runner only uses the interface |
| Gateway | `myp1/gateway` | Telegram today; the runner takes any async notifier |

`myp1/runner.py` is the only module where these meet. `myp1/app.py` is the only
module that knows which concrete implementation each seam gets.

## Quick start

```bash
git clone https://github.com/cry2222/my-p1.git && cd my-p1
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

cp .env.example .env      # defaults are paper mode; edit as you like
python -m myp1
```

Paper mode needs no exchange credentials — it pulls real prices from public
endpoints and simulates fills with fees and slippage applied against you.

### Backtest first

```bash
python scripts/backtest.py --synthetic 600 --fast 5 --slow 20
python scripts/backtest.py --csv data/btc-1m.csv --symbol BTC/USDT --verbose
```

The backtest runs the *same* runner, strategy and risk engine as live mode,
with only the market-data and execution seams swapped. CSV columns:
`timestamp,open,high,low,close,volume`.

### Telegram

1. Message [@BotFather](https://t.me/BotFather) → `/newbot` → copy the token.
2. Message [@userinfobot](https://t.me/userinfobot) → copy your numeric id.
3. Put both in `.env` as `MYP1_TELEGRAM_TOKEN` and `MYP1_TELEGRAM_OWNER_ID`.

Only that one chat id can issue commands. Everything else is logged and dropped.

| Command | Effect |
|---|---|
| `/status` | mode, position, PnL, ticks, uptime |
| `/position` | open position detail with mark price |
| `/pnl` | realized today, realized total, unrealized |
| `/fills` | last 10 fills |
| `/pause` | stop opening new positions; exits still run |
| `/resume` | allow new positions again |
| `/kill` | **halt everything**, including exits |
| `/revive` | release the kill switch |

The bot also pushes a message on every fill, every failed order, and every
kill-switch trip.

## Risk controls

Every order passes through `myp1/risk/engine.py`. There is no bypass path, and
the engine denies by default — if a limit cannot be evaluated, the order is
rejected rather than allowed through.

| Limit | Env var | Blocks |
|---|---|---|
| Position notional cap | `MYP1_MAX_POSITION_NOTIONAL` | oversized entries (order is shrunk to fit) |
| Equity fraction | `MYP1_RISK_FRACTION` | committing too much per trade |
| Daily loss limit | `MYP1_MAX_DAILY_LOSS` | new entries once the day is down that much |
| Daily order cap | `MYP1_MAX_ORDERS_PER_DAY` | a runaway loop |
| Slippage tolerance | `MYP1_MAX_SLIPPAGE_PCT` | trips the kill switch after a bad fill |
| Minimum notional | `MYP1_MIN_ORDER_NOTIONAL` | dust orders |

Three behaviours worth knowing:

- **Pause blocks entries but not exits.** A pause that trapped you in a
  position would not be a safety feature.
- **Kill blocks exits too.** It is a full stop, so an open position becomes
  yours to close by hand. That is the intent — use `/pause` if you want the
  bot to keep unwinding.
- **Kill switch state persists.** It lives in the journal, so restarting the
  process does not clear it.

## Going live

Live mode requires four things set together, or startup fails with an error
naming what is missing:

```bash
MYP1_MODE=live
MYP1_LIVE_CONFIRM=i-understand-this-trades-real-money
MYP1_API_KEY=...
MYP1_API_SECRET=...
# plus a working Telegram config — the kill switch must be reachable
```

On the exchange, create keys with **trading enabled, withdrawals disabled**,
IP-restricted to the host running the bot.

Run paper mode against your real symbol and timeframe for long enough to see
the strategy trade in conditions you did not design it for. `scripts/backtest.py`
tells you about the past; paper mode tells you about your plumbing.

> The bundled `ema_cross` strategy demonstrates the seam. It is not an edge —
> the backtest above underperforms buy-and-hold on a trending series, which is
> the honest result for a naive crossover. Replace it with your own.

## Development

```bash
pytest              # 85 tests, no network required
ruff check .
```

The test suite runs the entire pipeline through the replay source and paper
venue, so signal → risk → execution → journal → notify is covered end to end
without touching an exchange.

Adding a strategy:

1. Implement `evaluate(candles) -> Signal | None` and a `warmup` property.
2. Register it in `build_strategy()` in `myp1/app.py`.

Nothing else changes. That is the seam doing its job.

## License

MIT
