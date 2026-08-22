#!/usr/bin/env bash
# Background watcher: auto-open the reMarkable Paper Pro stream fullscreen the
# moment the tablet is plugged into USB, and close it again on unplug.
# Started automatically by the GNOME session (see the autostart entry).
#
# Uses native Google Chrome in a dedicated data dir so it is a separate,
# reliably-killable instance (Ubuntu's Firefox/Chromium are snaps, which can't
# do a clean dedicated kiosk, and --kiosk only works when it *starts* the
# browser instance).
#
# Part of remarkable_linlink. Installed to ~/.local/bin by install-host.sh.

URL="https://10.11.99.1:2001"
HOST="10.11.99.1"
PORT="2001"
DATA_DIR="$HOME/.config/remarkable-kiosk"
POLL=2          # seconds between checks

launch_kiosk() {
    google-chrome \
        --user-data-dir="$DATA_DIR" \
        --kiosk --app="$URL" \
        --ignore-certificate-errors --test-type \
        --ignore-gpu-blocklist --enable-unsafe-swiftshader \
        --no-first-run --no-default-browser-check \
        --password-store=basic --disable-session-crashed-bubble \
        >/dev/null 2>&1 &
    ff_pid=$!
}

prev="down"     # last known state, so we only act on transitions (edges)
ff_pid=""       # PID of the kiosk Chrome we launched

while true; do
    if nc -z -w1 "$HOST" "$PORT" 2>/dev/null; then
        state="up"
    else
        state="down"
    fi

    if [ "$state" = "up" ] && [ "$prev" = "down" ]; then
        # Tablet just appeared -> open the stream fullscreen.
        launch_kiosk
    elif [ "$state" = "down" ] && [ "$prev" = "up" ]; then
        # Tablet just went away -> close the kiosk we opened.
        if [ -n "$ff_pid" ] && kill -0 "$ff_pid" 2>/dev/null; then
            kill "$ff_pid" 2>/dev/null
            sleep 3
            kill -9 "$ff_pid" 2>/dev/null   # force if still alive
        fi
        ff_pid=""
    fi

    prev="$state"
    sleep "$POLL"
done
