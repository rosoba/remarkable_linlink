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
7. **A tablet OS update wipes the systemd unit.** Updates replace the whole root
   partition; `/etc/systemd/system/goMarkableStream.service` vanishes → `:2001`
   closed → no kiosk, while `:22` still works. Binary/config/JWT secret survive in
   `/home/root` (so no re-login). Symptom = SSH up, stream down. Fix: `rm-heal.sh`
   (re-runs `goMarkableStream install` using the surviving binary); the watcher
   runs it automatically. `/home/root` persists across updates; `/etc` does not.
8. **"active" service ≠ streaming.** After a firmware update goMarkableStream can
   start yet hang BEFORE binding `:2001` — its framebuffer scan blocks on a stale
   xochitl (journal ends at "JWT: Loaded secret key", no "Serving on"). systemd
   shows `active` the whole time. Fix: `systemctl restart xochitl` then the
   service (rm-heal.sh does this automatically when `:2001` stays closed). Also:
   check `:2001` from the HOST (`nc -z`) — the tablet's busybox `ss` does NOT
   list the IPv6 `[::]:2001` listener, so a tablet-side check reads falsely dead.

## Files
- `install-host.sh` — host installer (Chrome, scripts, autostart, desktop icon). Idempotent.
- `setup-tablet.sh [ip]` — from host over SSH: fetch RMPRO binary → scp → install service →
  apply fixes (tailscale dir, token lifetime) → restart.
- `scripts/remarkable-stream-watch.sh` — plug/unplug watcher (poll `nc -z 10.11.99.1 2001`,
  edge-triggered; opens kiosk on up, kills it on down).
- `scripts/remarkable-stream.sh` — manual launcher (30s wait-for-tablet, then kiosk).
- `scripts/rm-pull.py` — wired library mirror (tablet→local, read-only on tablet).
  Rebuilds the real folder/name tree from each `.metadata` (`parent` UUIDs); copies
  original PDFs/EPUBs only. Handwritten `.rm` notebooks are listed, not exported.
- `scripts/rm-push.py` — wired upload (add-only): writes `<uuid>.{pdf,metadata,content}`
  then `systemctl restart xochitl`. Never deletes.
- `scripts/rm-render.py` — export handwritten notebooks (`.rm` v6) to PDF offline.
  Self-managing venv (`rmc`+`rmscene`+`cairosvg`+`pypdf`) under
  `~/.config/remarkable-linlink/rmvenv`; re-execs into it (detect via `sys.prefix`,
  NOT realpath — realpath collapses venvs to the base python). rmc 0.3.0 crashes on
  Paper Pro `HIGHLIGHT` colour id 9 → we patch `RM_PALETTE` to `.get(id, yellow)`.
  rmc's own PDF path uses snap Inkscape (sandboxed, fails) → we go `.rm`→SVG (rmc)
  →PDF (cairosvg, white bg)→merge (pypdf). Pure notebooks only; on-demand.
- `scripts/rm-annotate.py` — export annotated PDFs (source page + ink overlay).
  Shares rm-render's venv. Ink frame: PDF fits to width = rmc x∈[±`PAGE_W_PT`/2],
  y∈[0,`ph/s`]; overlay uses a "page + margins" canvas (union of page + ink extent)
  so margin notes aren't clipped. On-page + margin ink align well on Paper Pro.
  NOT handled: text highlights (`GlyphRange`, rmc skips them) and per-page zoom/pan
  (`customZoom*` in `.content`) — a zoomed page's ink may be offset.
- `scripts/rm-heal.sh` — restore the service after an OS update (see fact #7),
  reusing the surviving `/home/root` binary. Watcher runs it when `:22` up + `:2001`
  down; also runnable by hand. Distinct from `setup-tablet.sh` (which re-copies the
  binary and is for first-time install).
- `scripts/remlink.py` — the **remlink** manager (Tkinter, phase 1); installed as
  `~/.local/bin/remlink` + an app-menu entry, and opened on plug-in by the watcher
  (singleton via `pgrep -f`). Thin wrapper over the rm-* CLIs (parses their stdout
  for progress); holds NO logic. Needs `python3-tk`. Roadmap: `docs/concepts/status-app.md`.
  The "Tablet (SSH)" dot does a real `ssh … true` auth check (green = key logs in,
  orange = `:22` reachable but key NOT authorized → run `ssh-copy-id`). "Restart
  kiosk" kills all kiosk windows by data-dir + relaunches one via
  `remarkable-stream.sh` — the fix for "Rate limited" (two viewers). "Heal service"
  runs in its own thread (usable even while a sync runs — it's SSH-independent of
  the pull/render); "Interrupt" stops the running sync. Library counts
  come from `~/.cache/remlink-state.json`, written by the rm-* tools on full runs.
- `scripts/remlink_index.py` — shared SQLite cache-index (`~/remarkable_mirror/
  .remlink-index.db`). Tools import it via `sys.path.insert(dirname(__file__))`
  (installed alongside in `~/.local/bin`). Keyed `(uuid, kind)` where kind ∈
  pdf/notebook/annotated; stores tablet `lastModified` + `processed_at`. rm-pull
  registers all docs (denominators) + prunes deleted; render/annotate skip via
  `is_current` (re-render when tablet `lastModified` newer; adopt pre-existing
  outputs) and `mark`. remlink reads `counts()`. Pure cache: delete → filesystem
  "skip if output exists" fallback, rebuilt on next pull. Replaced the old
  `~/.cache/remlink-state.json` aggregate.
- Auto-mirror: the watcher runs `rm-pull.py` on plug-in **iff** `~/remarkable_mirror`
  exists (opt-in). NEVER point bidirectional sync (Unison) at the xochitl store — it
  races the live app and can propagate deletes onto the tablet.

## If asked to extend
- Support rM1/rM2: same scripts; change tablet binary to `RM1`/`RM2`; skip Developer Mode.
- The tablet screen params (1632×2154, BGRA, flipped) are baked into the served page; the
  Chrome client needs no per-device config.
- Prefer editing `scripts/*` then re-running `install-host.sh` (it reinstalls from `scripts/`).
