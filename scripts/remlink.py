#!/usr/bin/env python3
"""remlink — tiny status/control panel for remarkable_linlink (phase 1).

A thin Tkinter front-end over the rm-* CLIs. It shows the link state at a glance
and runs the workflows by button — it holds NO logic of its own, it just shells
out and parses the tools' stdout for progress. See docs/concepts/status-app.md.

Requires python3-tk (install-host.sh installs it). Launches from the app grid as
"remlink", by the `remlink` command, or automatically on USB plug-in.
"""
import os
import queue
import re
import socket
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, scrolledtext

HOST = "10.11.99.1"
STREAM_PORT = 2001
SSH_PORT = 22
KIOSK_DIR = os.path.expanduser("~/.config/remarkable-kiosk")
MIRROR_DIR = os.path.expanduser("~/remarkable_mirror")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import remlink_index as idx  # noqa: E402

# green=done/healthy, red=none/down, orange=partial/needs-heal, blue=processing, grey=unknown
GREEN, RED, GREY, ORANGE, BLUE = "#2e7d32", "#c62828", "#9e9e9e", "#ef6c00", "#1565c0"


def _tool(name):
    """Prefer the installed tool; fall back to the repo's scripts/ dir."""
    inst = os.path.expanduser(f"~/.local/bin/{name}")
    if os.path.exists(inst):
        return inst
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), name)


def port_open(host, port, timeout=1.5):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def ssh_authorized(host):
    """True only if our key actually logs in — not just that :22 is reachable."""
    try:
        return subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=3",
             "-o", "StrictHostKeyChecking=accept-new", f"root@{host}", "true"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
    except OSError:
        return False


def kiosk_running():
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                cl = f.read().replace(b"\0", b" ").decode("utf-8", "replace")
        except OSError:
            continue
        if f"--user-data-dir={KIOSK_DIR}" in cl and "zygote" not in cl:
            return True
    return False


class App:
    def __init__(self, root):
        self.root = root
        root.title("remlink — reMarkable Manager")
        root.geometry("980x760")
        root.minsize(760, 560)
        self.q = queue.Queue()          # (kind, payload) from worker threads
        self.proc = None                # running action subprocess
        self.total = None
        self.done = 0

        self.running_category = None     # which library row is mid-task (blue)
        self.healing = False             # a heal is in flight (independent of proc)

        # --- status: two vertical groups side by side ---
        status = ttk.Frame(root)
        status.pack(fill="x", padx=8, pady=(8, 4))

        conn = ttk.LabelFrame(status, text="Connection")
        conn.pack(side="left", fill="both", expand=True, padx=(0, 4))
        self.conn_dots = {}
        for key in ("Tablet (SSH)", "Stream :2001", "Kiosk", "Service"):
            row = ttk.Frame(conn); row.pack(fill="x", padx=6, pady=1, anchor="w")
            dot = tk.Label(row, text="●", fg=GREY, font=("", 12)); dot.pack(side="left")
            ttk.Label(row, text=key).pack(side="left", padx=(4, 0))
            self.conn_dots[key] = dot

        lib = ttk.LabelFrame(status, text="Library (bookkept)")
        lib.pack(side="left", fill="both", expand=True, padx=(4, 0))
        self.lib_rows = {}
        for key in ("PDFs", "Notebooks", "Annotated"):
            row = ttk.Frame(lib); row.pack(fill="x", padx=6, pady=1, anchor="w")
            dot = tk.Label(row, text="●", fg=GREY, font=("", 12)); dot.pack(side="left")
            ttk.Label(row, text=key, width=10, anchor="w").pack(side="left", padx=(4, 0))
            val = tk.Label(row, text="—"); val.pack(side="left")
            self.lib_rows[key] = (dot, val)

        self.hint = ttk.Label(root, text="", foreground=GREY)
        self.hint.pack(anchor="w", padx=10)

        # --- actions ---
        act = ttk.Frame(root)
        act.pack(fill="x", padx=8, pady=4)
        self.buttons = []      # the long-running syncs (disabled while one runs)
        specs = [
            ("Pull now", [_tool("rm-pull.py"), MIRROR_DIR], "Pulling", "pull"),
            ("Render notebooks", [_tool("rm-render.py"), MIRROR_DIR], "Rendering notebooks", "render"),
            ("Render annotations", [_tool("rm-annotate.py"), MIRROR_DIR], "Rendering annotations", "annotate"),
        ]
        for label, cmd, title, cat in specs:
            b = ttk.Button(act, text=label,
                           command=lambda c=cmd, t=title, k=cat: self.run(c, t, k))
            b.pack(side="left", padx=3)
            self.buttons.append(b)
        # Heal is independent (tablet service, over SSH) — stays clickable during a sync
        ttk.Button(act, text="Heal service", command=self.heal).pack(side="left", padx=3)
        ttk.Button(act, text="Restart kiosk", command=self.restart_kiosk).pack(side="left", padx=3)
        ttk.Button(act, text="Open mirror", command=self.open_mirror).pack(side="left", padx=3)
        self.stop_btn = ttk.Button(act, text="Interrupt", command=self.stop, state="disabled")
        self.stop_btn.pack(side="right", padx=3)

        self.counter = ttk.Label(root, text="idle", font=("", 10, "bold"))
        self.counter.pack(anchor="w", padx=10)

        # --- log ---
        self.log = scrolledtext.ScrolledText(root, height=16, state="disabled", wrap="word",
                                             font=("monospace", 9))
        self.log.pack(fill="both", expand=True, padx=8, pady=(2, 8))

        threading.Thread(target=self.poll_status, daemon=True).start()
        self.root.after(120, self.drain)

    # ---- status polling (background) ----
    def poll_status(self):
        while True:
            ssh = port_open(HOST, SSH_PORT)
            auth = ssh_authorized(HOST) if ssh else False
            stream = port_open(HOST, STREAM_PORT)
            conn = {
                "Tablet (SSH)": GREEN if auth else (ORANGE if ssh else GREY),
                "Stream :2001": GREEN if stream else (ORANGE if ssh else GREY),
                "Kiosk": GREEN if kiosk_running() else GREY,
                "Service": GREEN if stream else (RED if ssh else GREY),
            }
            self.q.put(("status", (conn, idx.counts(MIRROR_DIR), ssh, auth, stream)))
            time.sleep(3)

    # ---- run an action (background) ----
    def run(self, cmd, title, category=None):
        if self.proc is not None:
            return
        if not os.path.exists(cmd[0]):
            self._append(f"! tool not found: {cmd[0]}\n")
            return
        self.total, self.done = None, 0
        self.running_category = category
        self.counter.config(text=f"{title}…")
        for b in self.buttons:
            b.config(state="disabled")
        self.stop_btn.config(state="normal")
        self._append(f"\n$ {' '.join(cmd)}\n")
        threading.Thread(target=self._worker, args=(cmd, title), daemon=True).start()

    def _worker(self, cmd, title):
        env = dict(os.environ, PYTHONUNBUFFERED="1")
        try:
            self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                         text=True, bufsize=1, env=env)
            for line in self.proc.stdout:
                self.q.put(("line", (line, title)))
            self.proc.wait()
            rc = self.proc.returncode
        except Exception as e:                       # noqa: BLE001
            self.q.put(("line", (f"! error: {e}\n", title)))
            rc = -1
        self.proc = None
        self.q.put(("done", (title, rc)))

    def stop(self):
        if self.proc is not None:
            try:
                self.proc.terminate()
            except Exception:                        # noqa: BLE001
                pass

    def open_mirror(self):
        os.makedirs(MIRROR_DIR, exist_ok=True)
        subprocess.Popen(["xdg-open", MIRROR_DIR])

    def heal(self):
        """Reinstall the tablet stream service — independent of a running sync."""
        if self.healing:
            return
        self.healing = True
        self._append("\n$ rm-heal.sh (reinstall tablet stream service)\n")
        threading.Thread(target=self._heal_worker, daemon=True).start()

    def _heal_worker(self):
        cmd = [_tool("rm-heal.sh"), HOST]
        env = dict(os.environ, PYTHONUNBUFFERED="1")
        try:
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 text=True, bufsize=1, env=env)
            for line in p.stdout or []:
                self.q.put(("line", (line, "Heal")))
            p.wait()
            self.q.put(("line", (f"(heal finished, exit {p.returncode})\n", "Heal")))
        except OSError as e:
            self.q.put(("line", (f"! heal error: {e}\n", "Heal")))
        self.healing = False

    def restart_kiosk(self):
        """Fix 'Rate limited' by closing ALL kiosk windows, then opening exactly one."""
        subprocess.run(["pkill", "-f", f"--user-data-dir={KIOSK_DIR}"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        launcher = _tool("remarkable-stream.sh")
        if os.path.exists(launcher):
            subprocess.Popen([launcher], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self._append("\n(restart kiosk: closed duplicate viewers, opening one)\n")

    # ---- main-thread queue drain ----
    def drain(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "status":
                    conn, counts, ssh, auth, stream = payload
                    for key, color in conn.items():
                        self.conn_dots[key].config(fg=color)
                    self.update_library(counts)
                    if not ssh:
                        hint = "tablet not connected"
                    elif not auth:
                        hint = "SSH key not authorized — run:  ssh-copy-id root@10.11.99.1"
                    elif not stream:
                        hint = "service down — click Heal"
                    else:
                        hint = "streaming — kiosk should be open"
                    self.hint.config(text=hint)
                elif kind == "line":
                    line, title = payload
                    self._append(line)
                    self._progress(line, title)
                elif kind == "done":
                    title, rc = payload
                    self.counter.config(text=f"{title}: {'done' if rc == 0 else f'exit {rc}'}"
                                              + (f" ({self.done})" if self.done else ""))
                    for b in self.buttons:
                        b.config(state="normal")
                    self.stop_btn.config(state="disabled")
                    self.running_category = None
                    self.update_library(idx.counts(MIRROR_DIR))   # reflect what the tool wrote
        except queue.Empty:
            pass
        self.root.after(120, self.drain)

    def update_library(self, counts):
        rows = {"PDFs": ("pdf", "pull"), "Notebooks": ("notebook", "render"),
                "Annotated": ("annotated", "annotate")}
        for label, (kind, cat) in rows.items():
            dt = counts.get(kind) if counts else None
            done, total = dt if dt else (None, None)
            self._lib(label, done, total, cat)

    def _lib(self, key, done, total, category):
        dot, val = self.lib_rows[key]
        if self.running_category == category:
            dot.config(fg=BLUE); val.config(text="processing…"); return
        if total is None:                       # no index yet / unknown
            dot.config(fg=GREY); val.config(text="—"); return
        val.config(text=f"{done}/{total}")
        dot.config(fg=GREEN if (total == 0 or done >= total)
                   else RED if done == 0 else ORANGE)

    def _progress(self, line, title):
        m = re.search(r"==>\s+(?:rendering|exporting)\s+(\d+)", line)
        if m:
            self.total = int(m.group(1))
        s = line.strip()
        if s.startswith("+ ") or s.startswith("! "):
            self.done += 1
        if self.total:
            self.counter.config(text=f"{title}… {self.done}/{self.total}")
        elif self.done:
            self.counter.config(text=f"{title}… {self.done}")

    def _append(self, text):
        self.log.config(state="normal")
        self.log.insert("end", text)
        self.log.see("end")
        self.log.config(state="disabled")


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()
