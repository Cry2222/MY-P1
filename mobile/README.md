# MY-P1 mobile

React Native (Expo) app for watching and controlling the bot from a phone.

It talks to MY-P1 only over the HTTP control API — no shared code, no shared
database. That is the same replaceable-seam rule the bot uses internally: the
bot runs perfectly well with this app deleted, and this app can be replaced
without touching the bot.

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
dashboard later. The token goes in the device keystore (Keychain on iOS,
EncryptedSharedPreferences on Android) via `expo-secure-store`.

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
npm run typecheck
```

## Building for the stores

Expo Go covers development. For installable binaries:

```bash
npm install -g eas-cli
eas login
eas build --platform android --profile preview   # APK you can sideload
eas build --platform ios                         # needs an Apple developer account
```

An Android APK from `--profile preview` installs directly with no Play Store
listing, which is usually what you want for a personal tool.
