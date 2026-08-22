#!/usr/bin/env bash
# remarkable_linlink — TABLET setup, driven from the host over SSH.
#
# Downloads the goMarkableStream RMPRO binary (arm64, for the Paper Pro),
# copies it to the tablet, installs it as a systemd service, applies the two
# fixes we learned the hard way (missing .tailscale dir; long-lived JWT token),
# and restarts it.
#
# Prerequisites (see README.md):
#   - Developer Mode enabled on the tablet (required for SSH; WIPES the device).
#   - Passwordless SSH working:  ssh root@10.11.99.1  (no password prompt).
#
# Usage:   ./setup-tablet.sh [tablet_ip]      (default IP: 10.11.99.1)
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IP="${1:-10.11.99.1}"
SSH="ssh -o ConnectTimeout=5 root@$IP"
BIN_LOCAL="$REPO_DIR/bin/gomarkablestream-RMPRO"

echo "==> remarkable_linlink tablet setup (target root@$IP)"

# 0. Verify passwordless SSH
if ! $SSH true 2>/dev/null; then
    echo "ERROR: cannot SSH to root@$IP without a password."
    echo "  - Is the tablet plugged in and Developer Mode enabled?"
    echo "  - Did you run: ssh-copy-id root@$IP ?"
    exit 1
fi

# 1. Fetch the RMPRO binary (cached in ./bin so the tablet needs no internet)
if [ ! -f "$BIN_LOCAL" ]; then
    echo "  - Downloading goMarkableStream RMPRO binary..."
    VERSION="$(wget -q -O - https://api.github.com/repos/owulveryck/goMarkableStream/releases/latest \
        | grep tag_name | awk -F\" '{print $4}')"
    echo "    latest version: $VERSION"
    wget -q -O "$BIN_LOCAL" \
        "https://github.com/owulveryck/goMarkableStream/releases/download/$VERSION/gomarkablestream-RMPRO"
fi

# 2. Copy to the tablet
echo "  - Copying binary to the tablet..."
scp -q "$BIN_LOCAL" "root@$IP:/home/root/goMarkableStream"

# 3. Install as a service + apply fixes + restart
echo "  - Installing service and applying fixes on the tablet..."
$SSH 'bash -s' <<'REMOTE'
set -e
chmod +x /home/root/goMarkableStream
cd /home/root
./goMarkableStream install
# Fix 1: the installer references ReadWritePaths=/home/root/.tailscale in the
# systemd unit; if that dir is missing the service crash-loops (226/NAMESPACE).
mkdir -p /home/root/.tailscale
# Fix 2: make the JWT login token effectively never expire (10 years) so the
# kiosk stays logged in after a single login. (JWT must stay ENABLED — disabling
# it does NOT remove auth on the /funnel stream, it just breaks it -> 401.)
sed -i 's/^# *RK_JWT_TOKEN_LIFETIME=.*/RK_JWT_TOKEN_LIFETIME=87600h/' \
    /home/root/.config/goMarkableStream/env
systemctl daemon-reload
systemctl reset-failed goMarkableStream 2>/dev/null || true
systemctl restart goMarkableStream
sleep 2
echo "--- service state ---"
systemctl is-active goMarkableStream
grep -E 'RK_JWT_TOKEN_LIFETIME' /home/root/.config/goMarkableStream/env
REMOTE

cat <<EOF

==> Tablet setup complete.

Test it: plug the tablet into USB. A fullscreen Chrome kiosk should open at
https://$IP:2001. On the FIRST launch, log in once with the goMarkableStream
credentials (default admin / password unless you changed them in the env file);
the token then persists ~10 years in ~/.config/remarkable-kiosk.

Remember: only ONE viewer at a time (a second connection shows "Rate limited"
and a blank screen).
EOF
