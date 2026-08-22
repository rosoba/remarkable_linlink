#!/usr/bin/env python3
"""rm-status.py — tiny status/control panel for remarkable_linlink (phase 1).

A thin Tkinter front-end over the rm-* CLIs. It shows the link state at a glance
and runs the workflows by button — it holds NO logic of its own, it just shells
out and parses the tools' stdout for progress. See docs/concepts/status-app.md.

Requires python3-tk (install-host.sh installs it). Launches from the app grid as
"reMarkable Status".
"""
import os
import queue
import re
import socket
import subprocess
import threading
import tkinter as tk
from tkinter import ttk, scrolledtext

HOST = "10.11.99.1"
STREAM_PORT = 2001
SSH_PORT = 22
KIOSK_DIR = os.path.expanduser("~/.config/remarkable-kiosk")
MIRROR_DIR = os.path.expanduser("~/remarkable_mirror")

GREEN, RED, GREY, ORANGE = "#2e7d32", "#c62828", "#9e9e9e", "#ef6c00"


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


def mirror_stats():
    pdfs = 0
    for _root, _dirs, files in os.walk(MIRROR_DIR):
        pdfs += sum(1 for f in files if f.lower().endswith(".pdf"))
    listed = 0
    nb = os.path.join(MIRROR_DIR, "_notebooks-not-exported.txt")
    if os.path.exists(nb):
        with open(nb) as f:
            listed = sum(1 for ln in f if ln.strip() and "/" in ln)
    return pdfs, listed


class App:
    def __init__(self, root):
        self.root = root
        root.title("reMarkable Status")
        root.geometry("640x500")
        self.q = queue.Queue()          # (kind, payload) from worker threads
        self.proc = None                # running action subprocess
        self.total = None
        self.done = 0

        # --- status strip ---
        top = ttk.LabelFrame(root, text="Status")
        top.pack(fill="x", padx=8, pady=(8, 4))
        self.dots = {}
        for i, key in enumerate(("Tablet (SSH)", "Stream :2001", "Kiosk", "Service")):
            ttk.Label(top, text="●", foreground=GREY, font=("", 12)).grid(row=0, column=2 * i, padx=(8, 2), pady=6)
            self.dots[key] = top.grid_slaves(row=0, column=2 * i)[0]
            ttk.Label(top, text=key).grid(row=0, column=2 * i + 1, padx=(0, 6))
        self.mirror_lbl = ttk.Label(top, text="Mirror: …")
        self.mirror_lbl.grid(row=1, column=0, columnspan=8, sticky="w", padx=8, pady=(0, 6))

        # --- actions ---
        act = ttk.Frame(root)
        act.pack(fill="x", padx=8, pady=4)
        self.buttons = []
        specs = [
            ("Pull now", lambda: self.run([_tool("rm-pull.py"), MIRROR_DIR], "Pulling")),
            ("Render notebooks", lambda: self.run([_tool("rm-render.py"), MIRROR_DIR], "Rendering notebooks")),
            ("Render annotations", lambda: self.run([_tool("rm-annotate.py"), MIRROR_DIR], "Rendering annotations")),
            ("Heal service", lambda: self.run([_tool("rm-heal.sh"), HOST], "Healing service")),
        ]
        for label, cmd in specs:
            b = ttk.Button(act, text=label, command=cmd)
            b.pack(side="left", padx=3)
            self.buttons.append(b)
        ttk.Button(act, text="Open mirror", command=self.open_mirror).pack(side="left", padx=3)
        self.stop_btn = ttk.Button(act, text="Stop", command=self.stop, state="disabled")
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
        import time
        while True:
            ssh = port_open(HOST, SSH_PORT)
            stream = port_open(HOST, STREAM_PORT)
            st = {
                "Tablet (SSH)": GREEN if ssh else GREY,
                "Stream :2001": GREEN if stream else (ORANGE if ssh else GREY),
                "Kiosk": GREEN if kiosk_running() else GREY,
                "Service": GREEN if stream else (RED if ssh else GREY),
            }
            pdfs, listed = mirror_stats()
            self.q.put(("status", (st, pdfs, listed, ssh, stream)))
            time.sleep(3)

    # ---- run an action (background) ----
    def run(self, cmd, title):
        if self.proc is not None:
            return
        if not os.path.exists(cmd[0]):
            self._append(f"! tool not found: {cmd[0]}\n")
            return
        self.total, self.done = None, 0
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

    # ---- main-thread queue drain ----
    def drain(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "status":
                    st, pdfs, listed, ssh, stream = payload
                    for key, color in st.items():
                        self.dots[key].config(foreground=color)
                    hint = "" if stream else (" — needs heal" if ssh else " — unplugged")
                    self.mirror_lbl.config(
                        text=f"Mirror: {pdfs} PDFs · {listed} notebooks listed{hint}")
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
        except queue.Empty:
            pass
        self.root.after(120, self.drain)

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
