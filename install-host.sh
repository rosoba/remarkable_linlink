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
update-desktop-database "$APPS_DIR" 2>/dev/null || true

# 6. Start the watcher now (so you don't have to log out first)
echo "  - Starting the watcher for this session"
pkill -f remarkable-stream-watch.sh 2>/dev/null || true
nohup "$BIN_DIR/remarkable-stream-watch.sh" >/dev/null 2>&1 &

cat <<EOF

==> Host install complete.

Next:
  1. Enable Developer Mode on the reMarkable Paper Pro (WIPES the device —
     back up / sync to cloud first). Required for SSH.
  2. Plug the tablet in via USB and set up a passwordless SSH key:
        ssh-keygen -t rsa           # if you don't have a key yet
        ssh-copy-id root@10.11.99.1 # tablet root password: Settings ->
                                    # Help -> Copyrights and licenses (bottom)
  3. Install the streaming server onto the tablet (from this repo):
        ./setup-tablet.sh
  4. Plug in the tablet: a fullscreen Chrome kiosk opens. Log in ONCE with the
     goMarkableStream credentials; the token then persists ~10 years.

See README.md for details and troubleshooting.
EOF
