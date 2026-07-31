# MY-P1

Auto-trading bot with a Telegram control surface. This code can spend real
money — see [`AGENTS.md`](AGENTS.md) for the full working guide, which is
authoritative.

## Fast orientation

- Pipeline: `market data → strategy → position diff → risk → execution → journal → telegram`
- `myp1/runner.py` is the only module where components meet
- `myp1/app.py` is the only module that chooses implementations
- `myp1/config.py` is the only module that reads `os.environ`

## Non-negotiables

1. Every order passes `RiskEngine.assess`. No bypass path.
2. Live mode needs mode + confirm phrase + credentials + a reachable Telegram
   kill switch. Never add a shortcut.
3. `/pause` blocks entries only. `/kill` blocks everything including exits.
4. Journal before notify.
5. No secrets in the repo, in logs, or in commit messages.

## Commands

```bash
pytest                                              # 85 tests, offline
ruff check .
python scripts/backtest.py --synthetic 600          # exercise the real pipeline
python -m myp1                                      # run (paper by default)
```

## Acme

This repository is a Helix **target**, not part of the Acme suite. Run
`helix serve` from inside this directory. See
[`docs/acme-setup.md`](docs/acme-setup.md).
