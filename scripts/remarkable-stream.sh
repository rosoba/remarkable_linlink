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
        # Native Chrome in a dedicated data dir = a separate, reliably-killable
        # kiosk that persists its own login token. The GPU flags are a
        # portability safety net so WebGL renders even on machines where
        # hardware WebGL is blocklisted/broken (harmless where it already works).
        exec google-chrome \
            --user-data-dir="$DATA_DIR" \
            --kiosk --app="$URL" \
            --ignore-certificate-errors --test-type \
            --ignore-gpu-blocklist --enable-unsafe-swiftshader \
            --no-first-run --no-default-browser-check \
            --password-store=basic --disable-session-crashed-bubble
    fi
    sleep 1
done

# Not reachable — notify and exit.
MSG="reMarkable not reachable at $HOST:$PORT. Is it plugged in and powered on?"
notify-send "reMarkable Stream" "$MSG" 2>/dev/null
echo "$MSG" >&2
exit 1
