# Agent guide — MY-P1

MY-P1 is an auto-trading bot. Code here can place orders that spend real
money. That single fact drives every rule below.

## Read first

- [`README.md`](README.md) — architecture, seams, risk controls
- [`docs/acme-setup.md`](docs/acme-setup.md) — how this repo relates to the
  Acme suite (it is a Helix *target*, not a suite member)
- [`myp1/runner.py`](myp1/runner.py) — the only place components meet

## Architecture

Components communicate through protocols in `base.py` files, never by
importing each other's internals:

```
myp1/
  config.py              env → validated Config. The ONLY module reading os.environ.
  core/models.py         the types allowed to cross a seam
  marketdata/base.py     MarketDataSource  — ccxt live, CSV replay
  strategy/base.py       Strategy          — candles in, target exposure out
  risk/engine.py         RiskEngine        — the mandatory gate
  execution/base.py      ExecutionVenue    — paper or live
  state/journal.py       durable record and control state
  gateway/telegram_bot.py  control surface; holds no trading logic
  api/routes.py          route logic; BOTH servers delegate here
  api/server.py          FastAPI transport (desktop/server)
  api/lite.py            stdlib-only transport (on-device, no compiled deps)
  runner.py              the loop; owns no domain logic
  app.py                 composition root; the only module that picks implementations

mobile/                  Expo app. Talks to the API over HTTP only.
                         Never import across this boundary in either direction.
```

A change that makes two components import each other has broken the design,
even if the tests pass.

## Rules

**Risk is not optional.** Every order goes through `RiskEngine.assess`. Do not
add a path that reaches a venue without it. Do not add a config value that
disables a limit — `RiskConfig.validate()` rejects zero and negative limits on
purpose.

**Live mode stays hard to reach.** Four independent things gate it: mode, the
confirmation phrase, credentials, and a reachable kill switch (Telegram or the
control API). Do not add a shortcut, a default, or a "skip for testing" flag.
`LiveVenue` requires `armed=True` for the same reason.

**The API is an authenticated surface, always.** Every route except
`/api/health` requires the bearer token, compared in constant time. Do not add
an unauthenticated route that exposes account state, do not default the bind
address off loopback, and do not lower the 24-character token minimum. If you
add a route, add its authorisation test — the tests cover every route rather
than sampling.

**Two servers, one contract.** Behaviour goes in `api/routes.py`, never in a
transport. `server.py` (FastAPI) is for desktops and servers; `lite.py`
(stdlib only) is for phones, where pydantic-core cannot be compiled. Any change
to a route must keep `tests/test_api_contract.py` green — it runs every
assertion against both, which is what lets the mobile app be indifferent to
which one it is talking to. Do not add a dependency to `lite.py`; its whole
value is having none.

**Pause and kill mean different things.** Pause blocks entries, allows exits.
Kill blocks everything, exits included. Keep it that way — a pause that traps
a position is not a safety feature, and a kill switch that keeps trading is
not a kill switch.

**Strategies stay pure.** `evaluate(candles)` reads candles and returns a
target exposure. It does not read account state, place orders, or notify. A
strategy that needs position data is a signal the seam is in the wrong place.

**The journal is written before notification.** A crash between the two must
never lose a fill that really happened. Do not reorder this.

**Secrets never enter the repository.** No keys in code, tests, fixtures,
commit messages, or logs. `.env` is gitignored; keep it that way.

## Testing

```bash
pytest                          # 196 tests, no network
ruff check .
cd mobile && npm run typecheck
```

Every test runs offline. `ReplayMarketData` + `PaperVenue` exercise the real
runner, so new behaviour gets a real end-to-end test, not a mock of the thing
you changed.

New risk limits need tests covering both directions — that the limit blocks
what it should, and that it does not block exits it should not.

Before touching order flow, run a backtest and confirm it still trades:

```bash
python scripts/backtest.py --synthetic 600 --fast 5 --slow 20
```

## Adding things

**A strategy**: implement `evaluate` and `warmup`, register in
`build_strategy()` in `app.py`, add tests in `tests/test_strategy.py`. Touch
nothing else.

**An exchange**: usually zero code — `MYP1_EXCHANGE` accepts any ccxt id.

**A venue** (different broker, different API): implement `ExecutionVenue`,
register in `build_venue()`. If it is live-capable, gate it exactly as
`LiveVenue` is gated.

**A notifier** (Discord, email): the runner takes any
`Callable[[str], Awaitable[None]]`. No runner changes needed.

**An API route**: put the logic in `myp1/api/routes.py`, wire it into both
`server.py` and `lite.py`, mirror its shape in `mobile/src/api/types.ts`, and
add it to the contract tests.

## Mobile app

Colour rules there are not decoration. Profit is teal because green/red is
unreadable under deuteranopia (ΔE 4.5, needs 8); teal/red measures 11.7. Teal
and red mean *money* and nothing else — side and direction are words. Every
figure carries a sign, every state carries a label, so colour is never the only
channel. If you change a colour, re-validate it against the dark surface rather
than eyeballing it; the numbers and the reasoning are in `mobile/src/theme.ts`.

Add mobile packages with `npx expo install <name>`, never by editing a version
into `package.json`. A version an SDK generation off compiles, packages and
installs, then crashes on launch — `npm run check-sdk` guards this and runs in
CI before anything expensive.

Do not use `Alert.alert` for anything that matters. It is a no-op with buttons
under react-native-web, which once meant the kill switch silently did nothing
in the web preview. `ConfirmDialog` behaves identically on every platform and
can be driven by a test.

## Do not

- Widen the Telegram allowlist beyond `owner_chat_id`
- Add an unauthenticated API route that exposes account state
- Bind the API off loopback by default, or document exposing it publicly
- Log API keys, secrets, or full request bodies
- Add automatic retry around order submission — a retried market order can
  double a position. Failures are journalled and surfaced instead.
- Commit `data/`, `.env`, `node_modules/`, or anything under `workspace/`
