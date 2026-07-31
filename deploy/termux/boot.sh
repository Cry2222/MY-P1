#!/data/data/com.termux/files/usr/bin/bash
#
# Termux:Boot hook — starts the bot after the phone reboots.
#
# Install:
#   1. Install the Termux:Boot app from F-Droid (not Google Play)
#   2. Open it once, so Android grants it the boot permission
#   3. mkdir -p ~/.termux/boot
#      cp deploy/termux/boot.sh ~/.termux/boot/start-myp1.sh
#      chmod +x ~/.termux/boot/start-myp1.sh
#
# Edit REPO_DIR below if you cloned somewhere else.

REPO_DIR="$HOME/MY-P1"

termux-wake-lock

# Give the network a moment — the bot handles an unreachable exchange, but
# starting after connectivity exists avoids a burst of pointless errors.
sleep 30

cd "$REPO_DIR" || exit 1
exec bash deploy/termux/run.sh
