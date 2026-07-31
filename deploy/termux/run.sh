#!/data/data/com.termux/files/usr/bin/bash
#
# Start MY-P1 on the phone, with the pieces Android needs to leave it alone.
#
#   bash deploy/termux/run.sh
#
# The wake lock is not optional. Without it Android's Doze mode suspends the
# process within minutes of the screen going off, and a suspended trading bot
# is a position nobody is managing.

set -uo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_DIR"

RESTART_DELAY="${MYP1_RESTART_DELAY:-15}"
LOG_DIR="${MYP1_LOG_DIR:-$REPO_DIR/data}"
mkdir -p "$LOG_DIR"

log() { printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$1"; }

cleanup() {
  log "releasing wake lock"
  termux-wake-unlock 2>/dev/null || true
  exit 0
}
trap cleanup INT TERM

if command -v termux-wake-lock >/dev/null 2>&1; then
  termux-wake-lock
  log "wake lock acquired"
else
  log "WARNING: termux-wake-lock not found — Android will suspend this process"
fi

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
  log "loaded .env"
else
  log "WARNING: no .env found, using defaults (paper mode)"
fi

# Supervise: a phone drops its network constantly, and an unhandled crash at
# 3am should not mean the bot is simply gone in the morning. The journal
# carries position and kill-switch state across restarts, so coming back up is
# safe — it re-reads reality rather than assuming it is flat.
while true; do
  log "starting bot"
  python -m myp1 2>&1 | tee -a "$LOG_DIR/myp1.log"
  code=${PIPESTATUS[0]}

  if [ "$code" -eq 0 ]; then
    log "bot exited cleanly"
    break
  fi
  if [ "$code" -eq 2 ]; then
    # Config error — restarting will fail identically. Stop and let a human read it.
    log "configuration error (exit 2) — not restarting"
    break
  fi

  log "bot exited with code $code, restarting in ${RESTART_DELAY}s"
  sleep "$RESTART_DELAY"
done

cleanup
