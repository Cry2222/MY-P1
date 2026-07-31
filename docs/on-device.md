# Running the bot on your phone

No VPS. The bot runs on the Android device itself under Termux, and the app
connects to `http://127.0.0.1:8333` — the same phone. Nothing is exposed to
any network at all, which makes this the most private setup available.

```
┌─────────────────── your phone ───────────────────┐
│                                                  │
│   Termux                        MY-P1 app        │
│   ├── python -m myp1            └── HTTP ────┐   │
│   │   ├── trading loop                       │   │
│   │   └── control API ◀───── 127.0.0.1:8333 ─┘   │
│   └── journal (sqlite)                           │
│                                                  │
└──────────────────────┬───────────────────────────┘
                       │ only outbound traffic:
                       ▼ exchange market data + orders
```

## Read this first

**Android only.** iOS has no Termux equivalent and terminates long-running
background processes. There is no version of this that works on an iPhone —
an iPhone can only be the *client*, with the bot running elsewhere.

**Android actively fights you.** Doze mode, battery optimisation and the
low-memory killer all target exactly this kind of process. The steps below
mitigate that; they do not eliminate it. Expect the bot to be killed
occasionally on aggressive OEM ROMs — Xiaomi, Huawei, OnePlus and Samsung are
the usual offenders.

**Your phone is now infrastructure.** Battery dies, phone reboots, you drop it
in a sink — each of those is now an open position nobody is managing. The
journal means a restart recovers correctly, but only once the phone comes
back. If that risk is not acceptable to you, a €4/month VPS is the answer
([`deployment.md`](deployment.md)).

That is the honest trade. It is a real option, not a bad one — it is just one
where the reliability is yours to own.

## Setup

### 1. Install Termux

From **F-Droid**, not Google Play — the Play Store version is abandoned and
too old to work:

- Termux: https://f-droid.org/packages/com.termux/
- Termux:Boot (optional, for restart-after-reboot):
  https://f-droid.org/packages/com.termux.boot/

### 2. Install MY-P1

```bash
pkg install -y git
git clone https://github.com/cry2222/my-p1.git ~/MY-P1
cd ~/MY-P1
bash deploy/termux/install.sh
```

The installer sets up Python and ccxt, generates an API token, and writes an
on-device `.env`. **Copy the token it prints** — you need it in the app.

It deliberately does not install FastAPI. FastAPI needs pydantic-core, a
compiled Rust extension that usually fails to build under Termux. The bot
detects this and uses its dependency-free API server instead, which speaks the
identical protocol — the mobile app cannot tell the difference, and the test
suite proves it by running the same contract tests against both.

### 3. Stop Android from killing it

Do all three. Skipping any one of them means the bot dies when the screen
goes off.

**Battery optimisation exemption**

> Android Settings → Apps → Termux → Battery → **Unrestricted**

**Wake lock** — `run.sh` acquires this automatically. You can also enable it
from the Termux notification ("Acquire wakelock").

**Phone-specific settings** — check https://dontkillmyapp.com for your make.
Xiaomi and Huawei in particular need extra "autostart" permissions that are
not in the standard Android settings.

### 4. Run it

```bash
cd ~/MY-P1
bash deploy/termux/run.sh
```

`run.sh` holds a wake lock, loads `.env`, and restarts the bot if it crashes —
except on a configuration error, where restarting would just fail identically.

### 5. Connect the app

Open MY-P1, and enter:

- **Server address**: `http://127.0.0.1:8333`
- **API token**: the one the installer printed (`grep MYP1_API_TOKEN ~/MY-P1/.env`)

The setup screen has a **This phone** button that fills the address for you.

### 6. Survive reboots (optional)

With Termux:Boot installed and opened once:

```bash
mkdir -p ~/.termux/boot
cp ~/MY-P1/deploy/termux/boot.sh ~/.termux/boot/start-myp1.sh
chmod +x ~/.termux/boot/start-myp1.sh
```

## Reality check

| | On-device | VPS |
|---|---|---|
| Cost | free | ~€4/month |
| Setup | 20 min | 15 min |
| Survives phone reboot | with Termux:Boot | n/a |
| Survives dead battery | **no** | yes |
| Survives OS killing it | mitigated, not solved | yes |
| Network exposure | **none** | loopback + Tailscale |
| Battery cost | noticeable | none |

**Battery**: a 1-minute timeframe means an HTTP request every 20s plus a wake
lock. Expect a meaningful hit — roughly 5–15%/day on top of normal use. A
longer timeframe (`MYP1_TIMEFRAME=15m`, `MYP1_POLL_SECONDS=60`) cuts that a
lot, and for most strategies loses nothing.

## Recommendation

Run **paper mode on-device** as long as you like — the only thing at risk is
your battery, and it is a genuinely good way to learn the system.

For **live trading**, think hard about the dead-battery case. My honest advice
is a VPS for live and the phone for paper. If you do go live on-device:

- Keep `MYP1_MAX_POSITION_NOTIONAL` small enough that a stranded position does
  not matter much
- Use a longer timeframe so a few minutes offline is not significant
- Keep the phone on a charger
- Know how to close a position by hand on the exchange, from the exchange's
  own app

That last one is the real backstop. If the phone dies, the exchange app on
another device is how you get out.

## Troubleshooting

**App says "Cannot reach the bot"**
Check the bot is running (`ps aux | grep myp1` in Termux) and that the address
is exactly `http://127.0.0.1:8333`. Loopback cleartext is permitted by the
network security config the build plugin writes, so an APK from this repo's
workflow works as-is; a hand-rolled build that skipped the plugin will not.

**Bot stops when the screen goes off**
The wake lock is not held, or battery optimisation is still on. Check the
Termux notification says "wakelock held", then re-check Settings → Apps →
Termux → Battery → Unrestricted.

**`pip install ccxt` fails**
`pkg update && pkg upgrade` first, then retry. If a dependency wants a
compiler: `pkg install clang`.

**Killed after a few hours**
Almost always an OEM battery manager. https://dontkillmyapp.com has
per-manufacturer instructions.

**Bot restarts in a loop**
Read `data/myp1.log`. Exit code 2 is a config error and `run.sh` will not
retry it; anything else retries every 15s.
