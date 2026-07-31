#!/data/data/com.termux/files/usr/bin/bash
#
# One-time setup for running MY-P1 on an Android phone under Termux.
#
#   bash deploy/termux/install.sh
#
# Installs only what the bot needs on-device. FastAPI is deliberately NOT
# installed: it depends on pydantic-core, a compiled Rust extension that
# routinely fails to build under Termux. The bot detects its absence and uses
# the dependency-free API server instead, which speaks the identical protocol.

set -euo pipefail

BLUE=$'\033[0;34m'; GREEN=$'\033[0;32m'; YELLOW=$'\033[1;33m'; NC=$'\033[0m'
say() { printf '%s==>%s %s\n' "$BLUE" "$NC" "$1"; }
ok()  { printf '%s  ok%s %s\n' "$GREEN" "$NC" "$1"; }
warn(){ printf '%s  !!%s %s\n' "$YELLOW" "$NC" "$1"; }

if [ ! -d "$PREFIX" ] || ! command -v pkg >/dev/null 2>&1; then
  echo "This script must run inside Termux on Android." >&2
  exit 1
fi

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_DIR"

say "Updating Termux packages"
pkg update -y >/dev/null
pkg install -y python git >/dev/null
ok "python $(python --version 2>&1 | cut -d' ' -f2)"

say "Installing MY-P1"
# Core dependencies are ccxt and nothing else — all pure Python, no compiler
# needed. The 'server' extra (FastAPI) is deliberately skipped.
pip install --upgrade pip >/dev/null
pip install -e . >/dev/null
ok "myp1 + ccxt installed"

if pip install -e ".[telegram]" >/dev/null 2>&1; then
  ok "Telegram alerts available"
else
  warn "python-telegram-bot failed to install — that is fine."
  warn "The mobile app is your control surface; Telegram is optional."
fi

say "Preparing configuration"
mkdir -p data
if [ ! -f .env ]; then
  cp .env.example .env
  TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
  # On-device defaults: API on, bound to loopback, lite server, no Telegram.
  python - "$TOKEN" <<'PY'
import pathlib, sys
token = sys.argv[1]
path = pathlib.Path(".env")
text = path.read_text()
replacements = {
    "MYP1_API_ENABLED=false": "MYP1_API_ENABLED=true",
    "MYP1_API_TOKEN=": f"MYP1_API_TOKEN={token}",
    "MYP1_TELEGRAM_ENABLED=true": "MYP1_TELEGRAM_ENABLED=false",
}
for old, new in replacements.items():
    text = text.replace(old, new, 1)
text += "\n# Dependency-free API server (no FastAPI on-device).\nMYP1_API_SERVER=lite\n"
path.write_text(text)
PY
  chmod 600 .env
  ok ".env created with a generated API token"
  echo
  printf '  Your API token (put this in the app):\n\n    %s\n\n' "$TOKEN"
else
  warn ".env already exists — leaving it alone"
  echo
  printf '  Your API token:\n\n    %s\n\n' "$(grep '^MYP1_API_TOKEN=' .env | cut -d= -f2-)"
fi

say "Verifying"
if python -c "from myp1.api import resolve_backend; print(resolve_backend('auto'))" | grep -q lite; then
  ok "API backend resolves to 'lite' (no compiled dependencies)"
else
  warn "FastAPI is present; the full server will be used"
fi
python -m pytest -q tests/test_risk.py 2>/dev/null | tail -1 || warn "pytest not installed (fine for running, not for developing)"

cat <<EOF

${GREEN}Setup complete.${NC}

Next:

  1. Edit .env — set your symbol and risk limits:
       nano .env

  2. Start the bot:
       bash deploy/termux/run.sh

  3. In the MY-P1 app, connect to:
       http://127.0.0.1:8333
     with the token printed above.

  4. Keep it alive across reboots and Doze — read this, it matters:
       docs/on-device.md

EOF
