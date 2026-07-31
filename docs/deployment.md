# Deploying MY-P1

A trading bot has one hard requirement a normal app does not: **it must not
stop while it holds a position.** Everything below follows from that.

## Recommendation

**A small VPS running Docker Compose, with Tailscale for phone access.**

- Any 1 GB VPS is plenty — the bot is IO-bound on one HTTP poll per interval
- `restart: unless-stopped` brings it back after a crash or a host reboot
- The journal lives on a volume, so a restart recovers the real position
- Tailscale gives the phone a private route to the API with no open ports

Pick a region close to your exchange's API endpoint. Latency is not critical
for a candle-based strategy, but a host that cannot reach the exchange at all
is fatal — check before you commit to a provider.

## Docker Compose (recommended)

```bash
git clone https://github.com/cry2222/my-p1.git /opt/myp1
cd /opt/myp1
cp .env.example .env
nano .env           # set your keys, risk limits, and API token

docker compose up -d
docker compose logs -f
```

The compose file publishes the API to `127.0.0.1:8333` on the host only. That
is deliberate — see [Reaching it from your phone](#reaching-it-from-your-phone).

```bash
docker compose ps            # health status
docker compose restart bot   # restart, journal survives
docker compose down          # stop; the volume is kept
```

The journal lives in the `myp1-data` volume. Back it up — it is your trade
history and your tax record:

```bash
docker run --rm -v myp1-data:/data -v "$PWD":/backup alpine \
  tar czf /backup/myp1-journal-$(date +%F).tar.gz -C /data .
```

## systemd (no Docker)

```bash
sudo useradd --system --home /opt/myp1 myp1
sudo git clone https://github.com/cry2222/my-p1.git /opt/myp1
cd /opt/myp1
sudo python3 -m venv .venv && sudo .venv/bin/pip install -e .
sudo mkdir -p /etc/myp1 /opt/myp1/data
sudo cp .env.example /etc/myp1/myp1.env
sudo nano /etc/myp1/myp1.env

# Credentials must not be world-readable.
sudo chmod 600 /etc/myp1/myp1.env
sudo chown root:myp1 /etc/myp1/myp1.env
sudo chown -R myp1:myp1 /opt/myp1

sudo cp deploy/myp1.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now myp1
journalctl -u myp1 -f
```

## Reaching it from your phone

The control API can halt trading. **Do not open port 8333 to the internet.**
A bearer token is authentication, not a security boundary — anything reachable
from the open internet gets scanned within hours.

**Use Tailscale.** It is free for personal use, takes about five minutes, and
gives the phone a private encrypted route with no exposed ports:

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
tailscale ip -4        # e.g. 100.101.102.103
```

Install Tailscale on your phone, sign in to the same account, and point the
app at `http://100.101.102.103:8333`. For Docker, bind the published port to
the Tailscale interface instead of loopback:

```yaml
ports:
  - "100.101.102.103:8333:8333"
```

Alternatives, in rough order of preference:

| Option | Notes |
|---|---|
| **Tailscale / WireGuard** | Best. Private network, no open ports, works anywhere. |
| **SSH tunnel** | `ssh -L 8333:127.0.0.1:8333 user@host`. Fine on a laptop, awkward on a phone. |
| **Caddy + TLS + a domain** | Real TLS, but now you have a public endpoint to defend. Add IP allowlisting. |
| **Plain open port** | No. |

## Before you go live

Work down this list in order. Nothing here is optional if real money is involved.

1. **Run paper mode for a week** against your real symbol and timeframe. You
   are testing plumbing and uptime, not the strategy.
2. **Check restart recovery.** With a position open:
   `docker compose restart bot` — then confirm `/position` in the app matches
   what it was. The journal replays fills; if this is wrong, stop.
3. **Test the kill switch from the phone**, on cellular, with wifi off. If you
   cannot reach it in the place you will actually need it, it does not exist.
4. **Set exchange API keys correctly**: trading enabled, **withdrawals
   disabled**, IP-restricted to the VPS.
5. **Size the limits for real money.** `MYP1_MAX_POSITION_NOTIONAL` and
   `MYP1_MAX_DAILY_LOSS` should be amounts you would shrug at losing on the
   first day, not amounts that make the returns interesting.
6. **Start small.** Whatever number feels reasonable, use a tenth of it for the
   first week.

## Monitoring

The bot pushes to Telegram on every fill, failed order, and kill-switch trip.
That is the primary channel — a dashboard you have to remember to open is not
monitoring.

For host-level uptime, point any uptime checker at `/api/health`. It needs no
token and leaks nothing about the account.

Watch for these in the logs:

| Symptom | Meaning |
|---|---|
| `errors` climbing in `/api/status` | exchange or network trouble; 10 consecutive trips the kill switch |
| `order rejected: daily loss limit` | the day's loss cap did its job |
| `KILL SWITCH ENGAGED (slippage breach)` | fills landing far from signal prices — investigate before reviving |
| No fills for a long stretch | often correct; check `/status` shows ticks advancing |

## Updating

```bash
cd /opt/myp1
git pull
docker compose up -d --build     # or: sudo systemctl restart myp1
```

The journal persists across updates. If a release changes the schema, the
migration runs on first start — back up the volume first.

Prefer to update while flat. An update with a position open is safe (the
journal replays it) but leaves a window where nothing is managing the trade.
