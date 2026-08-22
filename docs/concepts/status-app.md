# Concept: a tiny status/control app for remarkable_linlink

**Status:** phase 1 built → `scripts/remlink.py`, installed as the `remlink`
command + app entry, and opened on plug-in by the watcher.
**Verdict:** low–moderate effort, worth it. Phase 2 (below) still open.

## Goal

A small, always-available Ubuntu desktop app that shows — at a glance — the state
of the reMarkable link and lets you trigger the workflows by button instead of by
memorising CLI flags:

- **Connection state:** tablet plugged in? stream (`:2001`) up? kiosk open?
  service healthy (or wiped by an OS update)?
- **Mirror state:** how many PDFs/EPUBs mirrored, when the last pull ran, how many
  notebooks / annotated PDFs have been rendered vs. remain.
- **Actions:** pull now, push a single file (file picker), render notebooks, render
  annotations, re-heal the service, open the mirror folder.
- **Progress:** live "N / M processed" while a long render runs.

## Why it's cheap to build

All the intelligence already exists as small, composable CLIs with predictable
stdout. The app is a **thin front-end** — it must not re-implement any logic:

| UI element            | Backed by                          | How progress is known |
|-----------------------|------------------------------------|-----------------------|
| Connection row        | `nc -z 10.11.99.1 2001` / `:22`    | same checks the watcher uses |
| "Pull now"            | `rm-pull.py`                       | parses `+ <file>` lines and the final `done: X copied, Y unchanged` |
| "Push file…"          | `rm-push.py FILE [-f folder]`      | exit code + final line |
| "Render notebooks"    | `rm-render.py [--name]`            | `+ <name>.pdf` per item, final `done: ok/skip/fail` |
| "Render annotations"  | `rm-annotate.py [--name]`          | same shape |
| "Reinstall service"   | `rm-heal.sh`                       | exit code + `active` |
| Mirror counts         | walk `~/remarkable_mirror`         | count `*.pdf` vs `_notebooks-not-exported.txt` |

Because every tool prints `==> done: N …` lines and one-item-per-line progress,
the UI can show real counters just by reading the subprocess output.

## Architecture

```
[Tk window]
  ├─ status poller (thread): nc :2001/:22 every ~3s, xochitl/service via ssh (lazy)
  ├─ action runner (thread): subprocess.Popen(rm-*), stream stdout -> log + counter
  └─ mirror scanner: count files in ~/remarkable_mirror on demand
```

- One process, no daemon. Reuses `~/.ssh/config` and the installed `~/.local/bin/rm-*`.
- Long tasks run in a worker thread so the window stays responsive; a Stop button
  kills the subprocess.
- Read-only-on-tablet guarantees are inherited from the CLIs (nothing new touches
  the device).

## Tech choice

| Option | Deps | Notes |
|--------|------|-------|
| **Tkinter** (recommended) | none (stdlib) | Tiny, launches anywhere, matches "keep it tiny". Plain but fine for a status panel. |
| GTK3 / PyGObject | `python3-gi` (usually present) | Native GNOME look; optional AppIndicator tray icon. More boilerplate. |
| Tray indicator only | AppIndicator ext | "Glance" via a colored icon, but GNOME needs an extension → fragile. |

**Recommendation:** a single-window **Tkinter** app (~250–350 lines): a status
strip at top (green/red dots for tablet / stream / kiosk / service), a row of
action buttons, a counter label, and a scrolling log pane. Ship a `.desktop`
entry via `install-host.sh` (same pattern as the existing kiosk icon) so it opens
from the app grid like any Ubuntu app.

## Effort & risk

- **MVP** (status row + Pull/Render buttons + log + counters): ~half a day.
- **Full** (push file picker, per-item progress bars, tray icon, settings): ~1 day.
- **Risk: low.** The hard parts (rendering, coordinate mapping, self-heal) are done
  and tested; this only shells out and parses text. Main care points: keep the UI
  thread free (worker threads), and don't duplicate any tool logic in the UI.

## Suggested MVP scope (phase 1)

1. Status strip: tablet `:22`, stream `:2001`, kiosk process, mirror file count.
2. Buttons: **Pull now**, **Render notebooks**, **Render annotations**, **Heal**.
3. Live log pane + "N/M" counter parsed from tool output.
4. `.desktop` launcher installed by `install-host.sh`.

Defer to phase 2: single-file push with a picker, `--name` filter box, per-tool
progress bars, and a tray/indicator icon.

## Open questions

- Auto-updating counters (poll every 3s) vs. refresh-on-open only? (Poll is nicer,
  costs a couple of `nc` probes.)
- Should "Render all" be gated behind a confirm (the full library is slow)? Likely yes.
