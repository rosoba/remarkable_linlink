#!/usr/bin/env bash
# remarkable_linlink — Ubuntu HOST installer.
#
# Installs Google Chrome (if missing), the kiosk launcher scripts, the GNOME
# autostart watcher, and a desktop icon. Idempotent: safe to re-run.
#
# Run from the repo root:   ./install-host.sh
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="$HOME/.local/bin"
AUTOSTART_DIR="$HOME/.config/autostart"
APPS_DIR="$HOME/.local/share/applications"
DESKTOP_DIR="$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")"

echo "==> remarkable_linlink host install"

# 1. Google Chrome (native .deb — the snap Firefox/Chromium cannot do a clean
#    dedicated kiosk, and native Chrome is reliably killable for auto-close).
if command -v google-chrome >/dev/null 2>&1; then
    echo "  - Google Chrome already installed: $(command -v google-chrome)"
else
    echo "  - Installing Google Chrome (needs sudo)..."
    tmp_deb="$(mktemp --suffix=.deb)"
    wget -q -O "$tmp_deb" https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
    sudo apt-get install -y "$tmp_deb"
    rm -f "$tmp_deb"
fi

# 2. Dependencies used by the scripts (nc for reachability, notify-send optional)
if ! command -v nc >/dev/null 2>&1; then
    echo "  - Installing netcat (needs sudo)..."
    sudo apt-get install -y netcat-openbsd
fi
# python3-tk: needed only by the optional status app (rm-status.py)
if ! python3 -c 'import tkinter' >/dev/null 2>&1; then
    echo "  - Installing python3-tk (for the status app; needs sudo)..."
    sudo apt-get install -y python3-tk
fi

# 2b. SSH access to the tablet — needed by the rm-* file tools and setup-tablet.sh.
#     RSA key (Paper Pro / rM2 reject ed25519), passphraseless so the background
#     watcher can use it non-interactively; plus an idempotent config block that
#     applies the legacy-algorithm options the tablet requires.
SSH_DIR="$HOME/.ssh"; SSH_CFG="$SSH_DIR/config"
mkdir -p "$SSH_DIR"; chmod 700 "$SSH_DIR"
if [ ! -f "$SSH_DIR/id_rsa" ]; then
    echo "  - Generating an RSA SSH key (~/.ssh/id_rsa)"
    ssh-keygen -t rsa -b 4096 -N "" -C "remarkable_linlink@$(hostname)" -f "$SSH_DIR/id_rsa" >/dev/null
fi
chmod 600 "$SSH_DIR/id_rsa" 2>/dev/null || true
if ! grep -qE '^[[:space:]]*Host[[:space:]]+10\.11\.99\.1[[:space:]]*$' "$SSH_CFG" 2>/dev/null; then
    echo "  - Adding ~/.ssh/config block for the tablet (10.11.99.1)"
    cat >> "$SSH_CFG" <<'SSHCFG'

Host 10.11.99.1
    User root
    HostKeyAlgorithms +ssh-rsa
    PubkeyAcceptedKeyTypes +ssh-rsa
    IdentityFile ~/.ssh/id_rsa
    IdentitiesOnly yes
    StrictHostKeyChecking accept-new
SSHCFG
    chmod 600 "$SSH_CFG"
fi

# 3. Launcher scripts
echo "  - Installing scripts to $BIN_DIR"
mkdir -p "$BIN_DIR"
install -m 755 "$REPO_DIR/scripts/remarkable-stream.sh"       "$BIN_DIR/remarkable-stream.sh"
install -m 755 "$REPO_DIR/scripts/remarkable-stream-watch.sh" "$BIN_DIR/remarkable-stream-watch.sh"
# Wired file-management tools (need passwordless SSH to the tablet; see README).
install -m 755 "$REPO_DIR/scripts/rm-pull.py"                 "$BIN_DIR/rm-pull.py"
install -m 755 "$REPO_DIR/scripts/rm-push.py"                 "$BIN_DIR/rm-push.py"
install -m 755 "$REPO_DIR/scripts/rm-render.py"               "$BIN_DIR/rm-render.py"
install -m 755 "$REPO_DIR/scripts/rm-annotate.py"            "$BIN_DIR/rm-annotate.py"
install -m 755 "$REPO_DIR/scripts/rm-heal.sh"                "$BIN_DIR/rm-heal.sh"
install -m 755 "$REPO_DIR/scripts/remlink.py"               "$BIN_DIR/remlink"
rm -f "$BIN_DIR/rm-status.py"   # clean up the pre-rename name, if present

# 4. Autostart entry (starts the plug-in watcher with the GNOME session)
echo "  - Installing autostart watcher to $AUTOSTART_DIR"
mkdir -p "$AUTOSTART_DIR"
cat > "$AUTOSTART_DIR/remarkable-stream-watch.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=reMarkable Stream Watcher
Comment=Auto-open the reMarkable screen stream when the tablet is plugged in
Exec=$BIN_DIR/remarkable-stream-watch.sh
X-GNOME-Autostart-enabled=true
NoDisplay=true
Terminal=false
EOF

# 5. Manual desktop icon (+ app menu entry)
echo "  - Installing desktop icon to $DESKTOP_DIR"
mkdir -p "$DESKTOP_DIR" "$APPS_DIR"
desktop_file_contents() {
cat <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=reMarkable Stream
Comment=Open the reMarkable Paper Pro screen share
Exec=$BIN_DIR/remarkable-stream.sh
Icon=video-display
Terminal=false
Categories=Utility;
EOF
}
desktop_file_contents > "$DESKTOP_DIR/remarkable-stream.desktop"
desktop_file_contents > "$APPS_DIR/remarkable-stream.desktop"
chmod +x "$DESKTOP_DIR/remarkable-stream.desktop"
gio set "$DESKTOP_DIR/remarkable-stream.desktop" metadata::trusted true 2>/dev/null || true

# 5b. remlink manager (app-menu entry)
echo "  - Installing remlink app entry to $APPS_DIR"
rm -f "$APPS_DIR/remarkable-status.desktop"   # clean up the pre-rename entry
cat > "$APPS_DIR/remlink.desktop" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=remlink
Comment=reMarkable link manager — status + pull / render / heal
Exec=$BIN_DIR/remlink
Icon=utilities-system-monitor
Terminal=false
Categories=Utility;
EOF
update-desktop-database "$APPS_DIR" 2>/dev/null || true

# 6. Start the watcher now (so you don't have to log out first)
echo "  - Starting the watcher for this session"
pkill -f remarkable-stream-watch.sh 2>/dev/null || true
nohup "$BIN_DIR/remarkable-stream-watch.sh" >/dev/null 2>&1 &

cat <<EOF

==> Host install complete.

SSH key (~/.ssh/id_rsa) and the tablet's ~/.ssh/config block are set up.

Next (only when linking a tablet to THIS computer — skip if already streaming):
  1. Enable Developer Mode on the reMarkable Paper Pro (WIPES the device —
     back up / sync to cloud first). Required for SSH.
  2. Plug the tablet in via USB and authorize this computer's key:
        ssh-copy-id root@10.11.99.1 # tablet root password: Settings ->
                                    # Help -> Copyrights and licenses (bottom)
  3. Install the streaming server onto the tablet (from this repo):
        ./setup-tablet.sh
  4. Plug in the tablet: a fullscreen Chrome kiosk opens. Log in ONCE with the
     goMarkableStream credentials; the token then persists ~10 years.

To update later:  git pull && ./install-host.sh   (idempotent).
See README.md for details and troubleshooting.
EOF
