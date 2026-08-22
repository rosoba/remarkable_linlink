#!/usr/bin/env bash
# Manual launcher: open the reMarkable Paper Pro screen stream fullscreen.
# Waits for the tablet's USB network to come up, then opens Chrome in kiosk.
#
# Part of remarkable_linlink. Installed to ~/.local/bin by install-host.sh.

URL="https://10.11.99.1:2001"
HOST="10.11.99.1"
PORT="2001"
DATA_DIR="$HOME/.config/remarkable-kiosk"

# Wait up to ~30s for the tablet to be reachable after plugging in.
for _ in $(seq 1 30); do
    if nc -z -w1 "$HOST" "$PORT" 2>/dev/null; then
        # Close any existing kiosk first: a second viewer on the same data dir
        # makes the server return "Rate limited" (blank screen). This guarantees
        # exactly one fresh, fullscreen (kiosk) instance.
        pkill -f -- "--user-data-dir=$DATA_DIR" 2>/dev/null || true
        sleep 1
        # Native Chrome in a dedicated data dir = a separate kiosk that persists
        # its own login token. The GPU flags are a portability safety net so
        # WebGL renders even where hardware WebGL is blocklisted/broken.
        # Plain `--kiosk URL` (positional), NOT --app=URL: on GNOME/X11 an app
        # window under --kiosk becomes a MAXIMIZED decorated window (panels stay);
        # --kiosk gives true fullscreen. --ozone-platform-hint=auto = native
        # Wayland on Wayland, X11 on X11.
        exec google-chrome \
            --user-data-dir="$DATA_DIR" \
            --kiosk \
            --ozone-platform-hint=auto \
            --ignore-certificate-errors --test-type \
            --ignore-gpu-blocklist --enable-unsafe-swiftshader \
            --no-first-run --no-default-browser-check \
            --password-store=basic --disable-session-crashed-bubble \
            "$URL"
    fi
    sleep 1
done

# Not reachable — notify and exit.
MSG="reMarkable not reachable at $HOST:$PORT. Is it plugged in and powered on?"
notify-send "reMarkable Stream" "$MSG" 2>/dev/null
echo "$MSG" >&2
exit 1
