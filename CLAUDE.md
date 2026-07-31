# MY-P1

Auto-trading bot with a Telegram control surface. This code can spend real
money — see [`AGENTS.md`](AGENTS.md) for the full working guide, which is
authoritative.

## Fast orientation

- Pipeline: `market data → strategy → position diff → risk → execution → journal → telegram / API`
- `myp1/runner.py` is the only module where components meet
- `myp1/app.py` is the only module that chooses implementations
- `myp1/config.py` is the only module that reads `os.environ`
- `mobile/src/engine/` is a TypeScript port of the same trading rules; keep it
  and the Python side decision-for-decision identical, tests included
- `mobile/src/source/` is the seam letting one screen read a local engine or a
  remote bot
- Two API servers share `myp1/api/routes.py`: `server.py` (FastAPI) and
  `lite.py` (stdlib only, for phones). Logic goes in routes.py.

## Non-negotiables

1. Every order passes `RiskEngine.assess`. No bypass path.
2. Live mode needs mode + confirm phrase + credentials + a reachable kill
   switch (Telegram or the API). Never add a shortcut.
3. `/pause` blocks entries only. `/kill` blocks everything including exits.
4. Journal before notify.
5. Every API route except `/api/health` requires the token. API stays on
   loopback by default.
6. Route behaviour lives in `api/routes.py` so both servers agree.
   `tests/test_api_contract.py` runs against both and must stay green.
7. No secrets in the repo, in logs, or in commit messages.

## Commands

```bash
pytest                                              # 196 tests, offline
ruff check .
python scripts/backtest.py --synthetic 600          # exercise the real pipeline
python scripts/demo_server.py                       # real bot + API, replayed candles
python scripts/demo_server.py --server lite         # the on-device path
python -m myp1                                      # run (paper by default)
cd mobile && npm test && npm run typecheck          # engine tests + types
cd mobile && npm start                              # the app
```

## Deployment

Server: Docker Compose (`docs/deployment.md`). Phone: Termux, Android only
(`docs/on-device.md`) — uses the lite API server since FastAPI's pydantic-core
will not compile there.

## Acme

This repository is a Helix **target**, not part of the Acme suite. Run
`helix serve` from inside this directory. See
[`docs/acme-setup.md`](docs/acme-setup.md).
