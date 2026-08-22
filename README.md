# remarkable_linlink

Stream a **reMarkable Paper Pro** screen to an **Ubuntu** computer, with a
one-click / plug-and-play fullscreen kiosk. Built around
[goMarkableStream](https://github.com/owulveryck/goMarkableStream).

**What you get:**
- Plug the tablet into USB → a fullscreen live view of the screen opens automatically.
- Unplug → the window closes automatically.
- A desktop icon + app-menu entry for launching manually.
- No login prompts after a one-time setup; no per-use fiddling.

Tested on: Ubuntu 24.04 (GNOME/Wayland, snap Firefox) + reMarkable Paper Pro
(codename *Ferrari*, `imx8mm-ferrari`), goMarkableStream v1.4.0.

---

## Why this exists / key facts (read once)

- **reStream does NOT support the Paper Pro.** Its device table only knows rM1/rM2;
  the Paper Pro reports machine string `reMarkable Ferrari` and has a different,
  color framebuffer. We use **goMarkableStream** (`RMPRO` build, arm64) instead.
- **Developer Mode is required for SSH on the Paper Pro, and enabling it FACTORY-RESETS
  (wipes) the tablet.** Back up / sync to the cloud first. (rM1/rM2 don't need this.)
- **The stream is HTTPS-only, self-signed, on port 2001.** Plain HTTP returns 400.
- **JWT auth must stay ENABLED.** Disabling `RK_JWT_ENABLED` does *not* remove auth —
  the `/funnel` frame endpoint still returns `401`, so the screen stays blank/reconnecting.
  Instead we keep JWT on and set a 10-year token lifetime, then log in once.
- **Only ONE viewer at a time.** A second simultaneous connection shows a
  **"Rate limited"** badge and a blank canvas. (If you see blank + "Rate limited",
  close the other browser/tab that's viewing the stream.)
- **A tablet OS update wipes the streaming service.** reMarkable updates replace
  the whole root partition, deleting the systemd unit in `/etc` — so after an
  update the tablet is reachable over SSH but `:2001` is closed and no kiosk opens.
  The binary, config and login token live in `/home/root` and survive (no
  re-login). The watcher auto-heals this (reinstalls via `rm-heal.sh`); you can
  also run `./setup-tablet.sh` or `rm-heal.sh` by hand.
- **Ubuntu's Firefox and Chromium are snaps**, which can't run a clean dedicated
  kiosk (`--kiosk` only applies when it *starts* the instance; custom-path profiles
  don't lock properly; PID-kill for auto-close is unreliable). So we use **native
  Google Chrome** in a dedicated `--user-data-dir` — reliable fullscreen + killable.

---

## Fast track for a NEW computer + NEW tablet

On the **Ubuntu computer**:
```bash
git clone https://github.com/rosoba/remarkable_linlink.git ~/remarkable_linlink
cd ~/remarkable_linlink
./install-host.sh     # Chrome, scripts, watcher, status app, desktop entries,
                      # + an RSA key and the tablet ~/.ssh/config block
```

`install-host.sh` is idempotent — to **update** later: `git pull && ./install-host.sh`.

On the **reMarkable Paper Pro** (only when linking a tablet to this computer):
1. **Enable Developer Mode** (Settings → General → Software / Help). ⚠️ This **wipes
   the device** — sync/back up first. Set a device password if prompted.
2. Plug in via USB. Find the SSH root password on the tablet:
   *Settings → Help → Copyrights and licenses* (scroll to the bottom).

Back on the **computer** (the key + `~/.ssh/config` block are already in place):
```bash
ssh-copy-id root@10.11.99.1       # authorize this computer; enter the tablet password once
./setup-tablet.sh                 # installs + configures goMarkableStream over SSH
```

First plug-in: the kiosk opens, **log in once** (goMarkableStream default is
`admin` / `password` unless you change it) → done forever after.

> **Adding a second computer** (tablet already streaming elsewhere): just
> `git clone … && ./install-host.sh`, then `ssh-copy-id root@10.11.99.1` while the
> tablet is plugged into *that* computer. No `setup-tablet.sh` needed — the tablet
> is already provisioned. `mkdir ~/remarkable_mirror` there if you want auto-mirror.

That's it. Steps that **cannot** be pre-done for you: enabling Developer Mode and
the one-time `ssh-copy-id` (needs the tablet password interactively).

---

## What each piece does

| File | Runs on | Purpose |
|------|---------|---------|
| `install-host.sh` | Ubuntu | Installs Chrome, the two scripts, the autostart watcher, and the desktop icon. Idempotent. |
| `setup-tablet.sh` | Ubuntu → tablet (SSH) | Downloads the RMPRO binary, copies it over, installs the systemd service, applies both fixes, restarts. |
| `scripts/remarkable-stream-watch.sh` | Ubuntu | Background watcher: opens the kiosk on plug-in, closes it on unplug (and mirrors PDFs if enabled). Autostarted by GNOME. |
| `scripts/remarkable-stream.sh` | Ubuntu | Manual launcher (desktop icon / app menu). |
| `scripts/rm-pull.py` | Ubuntu → tablet (SSH) | Mirror the library to a local folder (one-way, read-only on the tablet). |
| `scripts/rm-push.py` | Ubuntu → tablet (SSH) | Upload a PDF/EPUB to the tablet (add-only; never deletes). |
| `scripts/rm-render.py` | Ubuntu → tablet (SSH) | Export handwritten notebooks to PDF (offline; self-managing venv). |
| `scripts/rm-annotate.py` | Ubuntu → tablet (SSH) | Export annotated PDFs (source page + your ink, incl. margin notes) to PDF. |
| `scripts/rm-heal.sh` | Ubuntu → tablet (SSH) | Reinstall the stream service after a tablet OS update (auto-run by the watcher). |
| `scripts/remlink.py` | Ubuntu | The **remlink** manager GUI: link state + buttons for pull / render / heal. Opens on plug-in and from the app grid. |
| `bin/gomarkablestream-RMPRO` | (cached) | The tablet binary, downloaded by `setup-tablet.sh` (gitignored by default). |

Installed locations on the host:
- `~/.local/bin/remarkable-stream*.sh`
- `~/.config/autostart/remarkable-stream-watch.desktop`
- `~/Desktop/remarkable-stream.desktop` and `~/.local/share/applications/…`
- Chrome kiosk profile/token: `~/.config/remarkable-kiosk/`

On the tablet:
- `/home/root/goMarkableStream` (binary)
- `/etc/systemd/system/goMarkableStream.service`
- `/home/root/.config/goMarkableStream/env` (config)

---

## Usage

- **Plug in** → fullscreen live screen (already authenticated).
- **Unplug** → kiosk closes.
- **Manual open** → double-click the *reMarkable Stream* desktop icon, or search
  "reMarkable Stream" in the app grid.
- **Exit fullscreen** → `Alt+F4`.
- **Only one viewer at a time** (see key facts).

### Change the tablet login / port
Edit `/home/root/.config/goMarkableStream/env` on the tablet (uncomment and set
`RK_SERVER_USERNAME` / `RK_SERVER_PASSWORD`), then
`systemctl restart goMarkableStream`. Log in again once in the kiosk.

---

## Local file management (wired, no cloud)

reMarkable only offers cloud sync (with no Linux desktop app), so we manage files
directly over the same USB/SSH link. Two tools (also installed to `~/.local/bin`):

```bash
# Pull: mirror the whole library to a local folder tree with real names.
# ONE-WAY, read-only on the tablet -> it can never alter or delete tablet content.
# Incremental (skips unchanged), so it's safe to re-run.
./scripts/rm-pull.py ~/remarkable_mirror

# Push: add a PDF/EPUB to the tablet. ADD-ONLY -> never touches existing docs.
./scripts/rm-push.py paper.pdf                 # to the library root
./scripts/rm-push.py paper.pdf -f "Reading"    # into a top-level folder (created if absent)
```

**Requires** passwordless SSH to the tablet from this host (the `Host 10.11.99.1`
block in `~/.ssh/config` with `PubkeyAcceptedKeyTypes +ssh-rsa`; see setup).

**Handwritten notebooks** are *not* handled by `rm-pull.py` — they live in
reMarkable's `.rm` lines format, not PDF, so `rm-pull.py` only lists them in
`_notebooks-not-exported.txt`. Use `rm-render.py` (below) to export them.

### Export handwritten notebooks → PDF

```bash
./scripts/rm-render.py --list                 # list all notebooks
./scripts/rm-render.py --name "Defence"       # render matching notebooks
./scripts/rm-render.py                         # render ALL into ~/remarkable_mirror
```

A small cache-index (`~/remarkable_mirror/.remlink-index.db`, SQLite) records what
was rendered and the tablet `lastModified` it came from, so a re-run **re-renders
only notebooks you've edited on the tablet** (not everything) and remlink can show
accurate done/total counts. It's a pure cache — delete it and the tools fall back
to "skip if the output exists"; the next `rm-pull` rebuilds it.

Renders the `.rm` pages (including the Paper Pro's **v6 colour** format) to PDF,
entirely offline, and drops each into the mirror tree next to the pulled PDFs.
Read-only on the tablet. On first run it builds a private venv (`rmc`, `rmscene`,
`cairosvg`, `pypdf`) under `~/.config/remarkable-linlink/rmvenv` — no manual pip.

Caveats: only *pure* notebooks are rendered (annotated PDFs are skipped — merging
ink onto the source PDF is a separate job, see [`remarks`](https://github.com/lucasrla/remarks));
unknown pen colours fall back to highlighter-yellow and very new brush types may
render imperfectly. Legibility is generally excellent. It is **on-demand only**
(not run on plug-in — rendering the whole library is slow).

### Export annotated PDFs → PDF

```bash
./scripts/rm-annotate.py --list               # list annotated PDFs
./scripts/rm-annotate.py --name "Vicente"     # export matching docs
./scripts/rm-annotate.py                        # export ALL into ~/remarkable_mirror
```

For PDFs you drew *on*, this overlays your ink back onto the source page and
writes `<name> (annotated).pdf`. reMarkable lets you write in an expandable canvas
beside the page, so the output uses a **"page + margins"** canvas — margin notes
appear next to the page instead of being clipped. On-page marks (underlines,
arrows, circles) land in the right place. Shares the same venv as `rm-render.py`.

Limits (honest): **text highlights** (highlighter over the PDF's own text) are
*not* rendered — only pen/marker strokes; and **per-page zoom/pan is not applied**,
so a page you zoomed/panned while writing may be offset. For perfect fidelity
(incl. highlights) use reMarkable's own email/cloud export.

### Auto-mirror on plug-in (opt-in)

The watcher mirrors the library each time you plug the tablet in — but only if the
mirror directory exists. Enable it once:

```bash
mkdir -p ~/remarkable_mirror
```

To use a different location, set `REMARKABLE_MIRROR_DIR` in the autostart entry.
Progress is logged to `~/remarkable_mirror/.rm-pull.log`.

> **Do NOT point Unison / bidirectional sync at the tablet.** The on-device store
> is a live app database of interdependent UUID files; two-way sync races with
> `xochitl`, can propagate deletions onto the tablet (bypassing its trash), and
> wouldn't capture handwriting anyway. One-way pull (backup) + add-only push is
> the safe pattern. If you must automate, only ever sync tablet → local.

---

## Troubleshooting (hard-won)

| Symptom | Cause / fix |
|---------|-------------|
| `Unsupported reMarkable version: reMarkable Ferrari` | You're using reStream. It doesn't support the Paper Pro — use goMarkableStream (this repo). |
| Service crash-loops, `status=226/NAMESPACE`, log says `.tailscale: No such file or directory` | The unit's `ReadWritePaths=/home/root/.tailscale` points at a missing dir. `mkdir -p /home/root/.tailscale` (setup-tablet.sh does this). |
| Browser: "Unable to connect" on `10.11.99.1:2001` | You used `http://`. It's **https-only** — use `https://`. |
| Endless "Reconnecting (attempt n/10)" | Stale cached page after a config change (hard-reload), **or** JWT was disabled (re-enable it), **or** a second viewer is connected. |
| Blank canvas + **"Rate limited"** badge | Another viewer is connected. Close the other tab/browser — only one at a time. |
| Blank canvas, no "Rate limited" | Not logged in / token expired → log in again. (WebGL is fine; the flags cover GPU edge cases.) |
| Firefox "already running, not responding … use a different profile" | snap Firefox + custom profile path. We use native Chrome instead — don't launch the kiosk via snap Firefox. |
| Kiosk doesn't cover the whole screen — GNOME top bar / dock still show, window has a title bar | Caused by launching with `--app=URL`: under `--kiosk` that becomes a *maximized decorated* window on GNOME/X11. The launchers now use plain `--kiosk URL` (true fullscreen). If you customised the launch, drop `--app`. On stubborn **Wayland** sessions also log in on **Ubuntu on Xorg** or press **F11**. |
| `ssh` rejects the key (`no matching host key`, RSA "legacy") | Modern OpenSSH treats `ssh-rsa` as legacy. Add to `~/.ssh/config`: `Host 10.11.99.1` / `PubkeyAcceptedKeyTypes=+ssh-rsa` / `HostKeyAlgorithms=+ssh-rsa`. |
| reMarkable 2 (not Pro) SSH key | rM2 doesn't accept `ed25519` keys — use `rsa`/`ecdsa`. |
| Kiosk stops opening after a while; SSH works but `:2001` is closed; service `not-found` | A tablet **OS update wiped the systemd unit**. The watcher auto-heals via `rm-heal.sh`; or run `rm-heal.sh` / `./setup-tablet.sh` manually. Binary/token survive, so no re-login. |
| remlink's "Tablet (SSH)" dot is **orange**, or `rm-*` tools can't connect on a new computer | Port 22 is reachable but **this computer's key isn't authorized on the tablet**. Run `ssh-copy-id root@10.11.99.1` once (per computer). The dot turns green only when the key actually logs in. |
| "Rate limited" on a second computer after updating | A **stale pre-update kiosk** is still open → two viewers. Click **Restart kiosk** in remlink (closes duplicates, opens one), or `pkill -f -- '--user-data-dir=$HOME/.config/remarkable-kiosk'`. Do NOT delete the kiosk profile — that only drops your login. |
| Service shows `active` but `:2001` never opens; journal ends at "JWT: Loaded secret key" (no "Serving on") | goMarkableStream's framebuffer scan is **hung on a stale xochitl** (seen after firmware updates). `rm-heal.sh` now detects this and restarts xochitl + the service (strokes are saved on a clean stop). Wake the tablet screen if it persists. |

### Handy tablet commands (over SSH)
```bash
systemctl status goMarkableStream
journalctl -u goMarkableStream -n 30 --no-pager
grep -vE '^\s*#' /home/root/.config/goMarkableStream/env   # active settings
```

---

## Notes for other device variants
- **reMarkable 1 / 2:** no Developer Mode needed (SSH works out of the box); use the
  matching goMarkableStream device build (`RM1` / `RM2`) instead of `RMPRO`. The rest
  (kiosk scripts, one-viewer rule, JWT/token approach) is identical.
- **Wayland vs X11:** the watcher launches Chrome from the GNOME session (via autostart),
  so it inherits the display env on both.
