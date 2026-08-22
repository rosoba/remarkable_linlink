#!/usr/bin/env bash
# Background watcher: auto-open the reMarkable Paper Pro stream fullscreen the
# moment the tablet is plugged into USB, and close it again on unplug.
# Started automatically by the GNOME session (see the autostart entry).
#
# Uses native Google Chrome in a dedicated data dir so it is a separate kiosk
# (Ubuntu's Firefox/Chromium are snaps, which can't do a clean dedicated kiosk,
# and --kiosk only works when it *starts* the browser instance).
#
# Part of remarkable_linlink. Installed to ~/.local/bin by install-host.sh.

URL="https://10.11.99.1:2001"
HOST="10.11.99.1"
PORT="2001"
DATA_DIR="$HOME/.config/remarkable-kiosk"
POLL=2          # seconds between checks

# Optional: mirror the tablet's PDFs/EPUBs locally on plug-in. This is OPT-IN:
# it only runs if the mirror directory already exists AND rm-pull.py is installed.
# So a kiosk-only host (no mirror dir) is unaffected. The pull is ONE-WAY and
# read-only on the tablet (see rm-pull.py) -> it can never alter/delete tablet
# content. Create the dir to enable:  mkdir -p ~/remarkable_mirror
MIRROR_DIR="${REMARKABLE_MIRROR_DIR:-$HOME/remarkable_mirror}"
PULL_BIN="$HOME/.local/bin/rm-pull.py"

# Kill any kiosk Chrome using our data dir. This is how we both close on unplug
# AND avoid a second viewer: relaunching Chrome with an existing data dir would
# just open another window in the same instance -> two stream connections ->
# the server shows "Rate limited" and a blank screen. Matching the data dir also
# catches re-parented processes that PID tracking misses.
kill_kiosk() {
    pkill -f -- "--user-data-dir=$DATA_DIR" 2>/dev/null || true
}

launch_kiosk() {
    kill_kiosk          # ensure exactly one fresh, kiosk (fullscreen) instance
    sleep 1
    google-chrome \
        --user-data-dir="$DATA_DIR" \
        --kiosk --app="$URL" \
        --ignore-certificate-errors --test-type \
        --ignore-gpu-blocklist --enable-unsafe-swiftshader \
        --no-first-run --no-default-browser-check \
        --password-store=basic --disable-session-crashed-bubble \
        >/dev/null 2>&1 &
}

pull_mirror() {
    # opt-in guards: enabled only when both the dir and the tool are present
    [ -d "$MIRROR_DIR" ] || return 0
    [ -x "$PULL_BIN" ] || return 0
    # background + logged, so the kiosk opens without waiting on the copy
    "$PULL_BIN" "$MIRROR_DIR" --host "$HOST" >>"$MIRROR_DIR/.rm-pull.log" 2>&1 &
}

prev="down"     # last known state, so we only act on transitions (edges)

while true; do
    if nc -z -w1 "$HOST" "$PORT" 2>/dev/null; then
        state="up"
    else
        state="down"
    fi

    if [ "$state" = "up" ] && [ "$prev" = "down" ]; then
        launch_kiosk    # tablet plugged in -> open the stream fullscreen
        pull_mirror     # ...and mirror PDFs/EPUBs locally, if enabled
    elif [ "$state" = "down" ] && [ "$prev" = "up" ]; then
        kill_kiosk      # tablet unplugged -> close the kiosk
    fi

    prev="$state"
    sleep "$POLL"
done
