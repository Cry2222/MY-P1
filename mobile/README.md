# MY-P1 mobile

Self-contained Android trading app. The strategy runs **inside the app** —
install the APK and it trades, with nothing else to set up.

**Android only.** iOS terminates long-running background processes, so a
trading loop cannot survive there.

## Two modes

**Run on this phone** (default) — a TypeScript engine in `src/engine/` does the
whole pipeline locally: market data → strategy → position diff → risk →
paper execution → journal. Same architecture as the Python bot, same seams,
ported decision for decision so the two can be compared rather than assumed
equal.

**Connect to a server** — drive a Python bot over its HTTP control API
instead. Kept because the trade-off is real: a phone that runs out of battery
stops trading; a server does not.

Both go through `BotSource` (`src/source/`), so the dashboard never knows
which it is talking to.

## Background execution

Android suspends a normal app within minutes of it leaving the screen. The
engine therefore runs under a **foreground service** — the mechanism music
players use — which requires a permanent notification. That notification is
not a nuisance to hide: it is the honest signal that something on this phone
is trading.

`plugins/withForegroundService.js` declares the service type Android 14+
requires. It uses `specialUse` rather than the more obvious `dataSync`,
because since API 35 Android caps `dataSync` services at about six hours a
day and then stops them — which for a trading loop means quietly ceasing to
manage an open position, the worst failure mode there is.

## Run it

```bash
cd mobile
npm install
npm start          # then scan the QR code with Expo Go
```

You need the bot's API running and reachable. For development with no exchange
and no keys, start the demo server from the repo root:

```bash
python scripts/demo_server.py
# API   http://127.0.0.1:8333
# token dev-token-at-least-24-characters-long
```

That runs the real runner, real risk engine and real API against replayed
candles, so the app sees a genuinely trading bot.

> On a physical phone, `127.0.0.1` is the phone itself. Use your machine's LAN
> address (`http://192.168.1.x:8333`) and start the server with
> `--host 0.0.0.0`, or use Tailscale.

## Screens

**Setup** — server address and API token. The connection is verified against
the live bot before it is saved, so a typo fails here rather than as a dead
dashboard later. The token goes in the Android keystore
(EncryptedSharedPreferences) via `expo-secure-store`.

**Dashboard** — polls every 6s and on app foreground. Ordered the way it gets
read: state badges, then net P&L as a hero figure, then the price sparkline,
then position, controls, runtime, and fill history.

## Design decisions

**Profit is teal, not green.** Green/red is the worst pair available for this:
under deuteranopia it measures ΔE 4.5 in OKLab, far below the 8 needed to tell
two colours apart, and red/green colour blindness affects about 1 in 12 men.
Teal against the same red measures 11.7. The full set was validated against
the actual background rather than eyeballed — the numbers are in
`src/theme.ts`.

**Colour never carries meaning alone.** Every P&L figure has a `+`/`-` sign,
every position states long/flat/short in words, every badge is labelled. Teal
and red mean *money* and nothing else — side and direction are words, so the
two meanings never share the colour channel.

**Polling, not a socket.** A phone's connection drops constantly. A failed
poll shows a `STALE` badge; a dead socket shows a screen that silently lies.
The staleness indicator is the point.

**Kill needs confirmation.** A one-tap kill switch on a phone in a pocket is a
hazard. Pause does not — it is the reversible one.

**Chart chrome is absent on purpose.** One series, so no legend; the current
value is direct-labelled and the period change sits beside it. No grid, no
axis ticks, no label on every point. A sparkline answers "which way, roughly
how much".

## Structure

```
src/
  api/client.ts     typed API client, 8s timeout, auth-aware errors
  api/types.ts      mirrors myp1/api/server.py
  components/       primitives + Sparkline
  screens/          SetupScreen, DashboardScreen
  storage.ts        keystore-backed connection persistence
  theme.ts          validated palette and formatters
```

## Checks

```bash
npm test               # 49 engine tests, off-device
npm run check-sdk      # Expo-managed packages match the installed SDK
npm run typecheck
npm run bundle-check   # Metro + Hermes production bundle
```

`npm test` covers the parts that decide how money moves — position
accounting, indicators, the strategy and the risk gate — with `node --test`.
They mirror the Python suite's cases, so a disagreement between the two
engines shows up as a failing test rather than a different balance.


`check-sdk` is the one that matters most. A native module built against a
different SDK version compiles, packages and installs perfectly, then crashes
the app the moment it launches:

```
NoClassDefFoundError: expo/modules/kotlin/types/AnyTypeProvider
  at expo.modules.securestore.SecureStoreModule.definition
```

That was `expo-secure-store` 15.x sitting beside `expo-modules-core` 57.x —
an SDK generation apart, because the version had been written into
`package.json` by hand. **Always add packages with `npx expo install <name>`,
never by editing the version.** `expo install --check` is the canonical tool
but needs network; this script reads the SDK's own
`bundledNativeModules.json`, so it works offline too.

`bundle-check` runs the same bundling Gradle does when building a release APK.
It catches missing modules in about a minute; without it the same failure
surfaces seven minutes into a Gradle run as a Java stack trace.

`buffer` is a direct dependency for that reason: `react-native-svg` imports it
in `fetchData`, and while Expo Go tolerates the missing polyfill, a production
bundle does not.

## Building an APK

Expo Go covers development. For an installable binary, tag a release — GitHub
Actions builds it and attaches it to the release:

```bash
git tag v1.0.0 && git push origin v1.0.0
```

Or run the *Build Android APK* workflow manually from the Actions tab. See
[`docs/building-the-app.md`](../docs/building-the-app.md) for signing, local
builds, EAS, and the `cleartext_hosts` input.

### Native configuration

`mobile/android/` is generated by `expo prebuild` and gitignored. Native
settings live in `app.json` and `plugins/`:

- `plugins/withLoopbackCleartext.js` writes an Android network security config
  permitting plain HTTP to loopback (plus any host given via
  `MYP1_CLEARTEXT_HOSTS`) and nothing else. Android has blocked cleartext since
  API 28, so without this a standalone APK cannot reach a bot running on the
  same phone — and `android.usesCleartextTraffic` in `app.json` is silently
  ignored by current Expo prebuild.
- `scripts/configure-release-signing.py` repoints the generated release build
  at a real keystore when CI supplies one; prebuild wires it to the debug key.
