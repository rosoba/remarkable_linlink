#!/usr/bin/env bash
# rm-heal.sh — restore the goMarkableStream service after a reMarkable OS update.
#
# reMarkable OS updates replace the whole root partition, which wipes our systemd
# unit in /etc (the binary + config + JWT token in /home/root survive). Symptom:
# tablet reachable over SSH (:22) but the stream (:2001) is closed, so no kiosk.
#
# This re-runs the installer using the SURVIVING binary (no re-copy / no download)
# and re-applies the two fixes, then restarts. If the service starts but hangs
# before binding :2001 (its framebuffer scan stuck on a stale xochitl — also seen
# after firmware updates; log ends at "JWT: Loaded secret key" with no "Serving"),
# it restarts xochitl (a clean stop saves all strokes) and tries once more.
#
# The port check runs HOST-side (nc), matching what the kiosk actually needs —
# the tablet's busybox ss does not list the IPv6 [::]:2001 listener.
#
# Idempotent; safe to run anytime. The watcher calls it automatically.
#
# Usage:  rm-heal.sh [tablet_ip]      (default 10.11.99.1)
set -euo pipefail
HOST="${1:-10.11.99.1}"
SSH="ssh -o BatchMode=yes -o ConnectTimeout=10 root@$HOST"

wait_stream() {          # poll :2001 from the host for up to $1 seconds
    local i=0 limit="${1:-15}"
    while [ "$i" -lt "$limit" ]; do
        nc -z -w1 "$HOST" 2001 2>/dev/null && return 0
        sleep 1; i=$((i + 1))
    done
    return 1
}

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
systemctl is-active goMarkableStream
REMOTE

if wait_stream 15; then
    echo "rm-heal: stream is up (:2001 reachable)"
    exit 0
fi

echo "rm-heal: service up but :2001 not reachable — restarting xochitl + service"
$SSH 'systemctl restart xochitl && sleep 6 && systemctl restart goMarkableStream'

if wait_stream 20; then
    echo "rm-heal: stream is up after xochitl restart"
else
    echo "rm-heal: WARNING — :2001 still not reachable (wake the tablet screen and re-run)"
    exit 1
fi
