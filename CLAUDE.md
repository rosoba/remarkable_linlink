# remarkable_linlink — context for Claude

Purpose: reproducible setup to stream a **reMarkable Paper Pro** to **Ubuntu** as a
plug-and-play fullscreen kiosk. This file is the fast-orientation for future work.

## The stack (and why)
- **Server:** goMarkableStream (owulveryck) `RMPRO` build on the tablet, systemd service,
  HTTPS self-signed on `:2001`, WebGL client, JWT auth. Chosen because **reStream does
  not support the Paper Pro** (device reports `reMarkable Ferrari`, color framebuffer).
- **Client:** native **Google Chrome** kiosk (`--app --kiosk --user-data-dir=…`). NOT
  Firefox/Chromium — those are snaps on Ubuntu and can't do a clean, killable dedicated
  kiosk. Chrome instance is killable → the watcher closes it on unplug.

## Non-obvious facts (do not relearn these)
1. **Developer Mode is required for SSH on the Paper Pro and enabling it factory-resets
   the tablet.** rM1/rM2 do not need it.
2. **Do NOT disable JWT** (`RK_JWT_ENABLED=false`). It doesn't remove auth; `/funnel`
   still 401s → blank/reconnecting. Keep JWT on; set `RK_JWT_TOKEN_LIFETIME=87600h`
   (10y) and log in once — the token lives in Chrome's `~/.config/remarkable-kiosk`
   localStorage and persists.
3. **`226/NAMESPACE` crash-loop** after `goMarkableStream install`: the unit sets
   `ReadWritePaths=/home/root/.tailscale` but the dir doesn't exist → `mkdir -p` it.
4. **One viewer at a time.** Second connection → "Rate limited" + blank. The blank we
   chased was this, not WebGL (the GPU flags are just a portability safety net).
5. HTTPS-only (http → 400). Cert is self-signed → Chrome uses
   `--ignore-certificate-errors --test-type`.
6. SSH: RSA key (Paper Pro / rM2 reject ed25519); modern OpenSSH may need
   `PubkeyAcceptedKeyTypes=+ssh-rsa` in `~/.ssh/config`.

## Files
- `install-host.sh` — host installer (Chrome, scripts, autostart, desktop icon). Idempotent.
- `setup-tablet.sh [ip]` — from host over SSH: fetch RMPRO binary → scp → install service →
  apply fixes (tailscale dir, token lifetime) → restart.
- `scripts/remarkable-stream-watch.sh` — plug/unplug watcher (poll `nc -z 10.11.99.1 2001`,
  edge-triggered; opens kiosk on up, kills it on down).
- `scripts/remarkable-stream.sh` — manual launcher (30s wait-for-tablet, then kiosk).

## If asked to extend
- Support rM1/rM2: same scripts; change tablet binary to `RM1`/`RM2`; skip Developer Mode.
- The tablet screen params (1632×2154, BGRA, flipped) are baked into the served page; the
  Chrome client needs no per-device config.
- Prefer editing `scripts/*` then re-running `install-host.sh` (it reinstalls from `scripts/`).
