#!/usr/bin/env bash
# rm-heal.sh — restore the goMarkableStream service after a reMarkable OS update.
#
# reMarkable OS updates replace the whole root partition, which wipes our systemd
# unit in /etc (the binary + config + JWT token in /home/root survive). Symptom:
# tablet reachable over SSH (:22) but the stream (:2001) is closed, so no kiosk.
#
# This re-runs the installer using the SURVIVING binary (no re-copy / no download)
# and re-applies the two fixes, then restarts. Idempotent; safe to run anytime.
# The watcher calls it automatically; you can also run it by hand.
#
# Usage:  rm-heal.sh [tablet_ip]      (default 10.11.99.1)
set -euo pipefail
HOST="${1:-10.11.99.1}"
SSH="ssh -o BatchMode=yes -o ConnectTimeout=10 root@$HOST"

$SSH 'bash -s' <<'REMOTE'
set -e
cd /home/root
if [ ! -x goMarkableStream ]; then
    echo "rm-heal: binary /home/root/goMarkableStream missing — run setup-tablet.sh instead" >&2
    exit 1
fi
./goMarkableStream install
mkdir -p /home/root/.tailscale
sed -i 's/^# *RK_JWT_TOKEN_LIFETIME=.*/RK_JWT_TOKEN_LIFETIME=87600h/' \
    /home/root/.config/goMarkableStream/env 2>/dev/null || true
systemctl daemon-reload
systemctl reset-failed goMarkableStream 2>/dev/null || true
systemctl restart goMarkableStream
sleep 2
systemctl is-active goMarkableStream
REMOTE
