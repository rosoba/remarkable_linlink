#!/usr/bin/env python3
"""rm-render.py — export handwritten reMarkable notebooks to PDF over USB/SSH.

On-demand companion to rm-pull.py (which handles only PDFs/EPUBs). This renders
the tablet's `.rm` "lines" pages — including the Paper Pro's v6 colour format —
to PDF, entirely offline. Read-only on the tablet.

It self-manages a Python venv (rmc + rmscene + cairosvg + pypdf) under
~/.config/remarkable-linlink/rmvenv and re-execs itself inside it, so you don't
need to install anything by hand. First run takes a minute to build the venv.

Scope & caveats:
  - Only *pure* notebooks (no PDF/EPUB original) are rendered. Annotated PDFs are
    skipped (merging ink onto the source PDF is a separate job — see `remarks`).
  - The Paper Pro writes a newer format than rmscene fully knows; unknown pen
    colours fall back to a highlighter-yellow, and very new brush types may
    render imperfectly. Legibility is generally excellent (tested).

Usage:  ./rm-render.py [dest_dir] [--name SUBSTR] [--force] [--list] [--host IP]
        dest_dir defaults to ~/remarkable_mirror (rendered PDFs slot into the
        same tree next to the pulled originals).
"""
import argparse
import glob
import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import time

DATA_DIR = "/home/root/.local/share/remarkable/xochitl"
VENV = os.path.expanduser("~/.config/remarkable-linlink/rmvenv")
PKGS = ["rmc", "cairosvg", "pypdf"]
STATE_FILE = os.path.expanduser("~/.cache/remlink-state.json")


def write_state(section, data):
    """Merge one section into the shared remlink state file (best-effort)."""
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        st = {}
        if os.path.exists(STATE_FILE):
            try:
                st = json.load(open(STATE_FILE))
            except (json.JSONDecodeError, OSError):
                st = {}
        st[section] = {**data, "ts": int(time.time())}
        tmp = STATE_FILE + ".tmp"
        json.dump(st, open(tmp, "w"))
        os.replace(tmp, STATE_FILE)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# venv bootstrap: build it if missing, patch rmc's palette, then re-exec inside
# ---------------------------------------------------------------------------
def patch_rmc_palette():
    """Make rmc tolerate the Paper Pro's extra colour ids (e.g. HIGHLIGHT=9)."""
    for wt in glob.glob(os.path.join(VENV, "lib", "python*", "site-packages",
                                     "rmc", "exporters", "writing_tools.py")):
        src = open(wt).read()
        bad = "self.base_color = RM_PALETTE[base_color_id]"
        good = "self.base_color = RM_PALETTE.get(base_color_id, (255, 235, 60))"
        if bad in src:
            open(wt, "w").write(src.replace(bad, good))


def ensure_venv():
    py = os.path.join(VENV, "bin", "python")
    if os.path.abspath(sys.prefix) == os.path.abspath(VENV):
        return  # already inside our venv (realpath would collapse venvs -> base python)
    if not os.path.exists(py):
        print("==> first run: building render venv (rmc, cairosvg, pypdf)…")
        os.makedirs(os.path.dirname(VENV), exist_ok=True)
        subprocess.run([sys.executable, "-m", "venv", VENV], check=True)
        subprocess.run([py, "-m", "pip", "install", "-q", "--upgrade", "pip"], check=True)
        subprocess.run([py, "-m", "pip", "install", "-q", *PKGS], check=True)
        patch_rmc_palette()
    os.execv(py, [py, os.path.abspath(__file__), *sys.argv[1:]])


ensure_venv()
# from here on we are running inside the venv
import cairosvg          # noqa: E402
from pypdf import PdfWriter  # noqa: E402


# ---------------------------------------------------------------------------
# helpers (shared shape with rm-pull.py)
# ---------------------------------------------------------------------------
def ssh(host, cmd, binary=False):
    full = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", f"root@{host}", cmd]
    if binary:
        return subprocess.run(full, stdout=subprocess.PIPE, check=True).stdout
    return subprocess.run(full, capture_output=True, text=True, check=True).stdout


def sanitize(name):
    import re
    return re.sub(r'[\x00-\x1f/\\]', "_", (name or "").strip() or "(unnamed)")[:150]


def load_nodes(host):
    tar_bytes = ssh(host, f"cd {DATA_DIR} && tar cf - *.metadata", binary=True)
    nodes = {}
    with tarfile.open(fileobj=io.BytesIO(tar_bytes)) as tf:
        for m in tf.getmembers():
            f = tf.extractfile(m)
            if f is None:
                continue
            try:
                nodes[m.name[:-9]] = json.loads(f.read().decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                pass
    return nodes


def path_of(nodes, uuid, _seen=None):
    _seen = _seen or set()
    if uuid in ("", "trash") or uuid in _seen:
        return None if uuid == "trash" else []
    n = nodes.get(uuid)
    if not n or n.get("deleted"):
        return None
    _seen.add(uuid)
    parent = path_of(nodes, n.get("parent", ""), _seen)
    return None if parent is None else parent + [sanitize(n["visibleName"])]


def page_order(content_json, rm_files):
    """Return .rm page filenames in document order (best effort)."""
    have = {os.path.splitext(os.path.basename(p))[0]: p for p in rm_files}
    try:
        ids = [pg["id"] for pg in content_json["cPages"]["pages"]]
        ordered = [have[i] for i in ids if i in have]
        if ordered:
            return ordered
    except (KeyError, TypeError):
        pass
    return sorted(rm_files)


def render_notebook(host, uuid, out_pdf):
    """Pull one notebook's pages and render them to a single PDF. True on success."""
    tmp = tempfile.mkdtemp(prefix="rmrender-")
    try:
        subprocess.run(["scp", "-q", "-r", f"root@{host}:{DATA_DIR}/{uuid}", tmp], check=True)
        subprocess.run(["scp", "-q", f"root@{host}:{DATA_DIR}/{uuid}.content", tmp], check=True)
        rm_files = glob.glob(os.path.join(tmp, uuid, "*.rm"))
        if not rm_files:
            return False
        content = json.load(open(os.path.join(tmp, f"{uuid}.content")))
        writer = PdfWriter()
        for rm in page_order(content, rm_files):
            svg = rm + ".svg"
            rmc = os.path.join(VENV, "bin", "rmc")
            r = subprocess.run([rmc, "-t", "svg", rm, "-o", svg],
                               capture_output=True, text=True)
            if r.returncode != 0 or not os.path.exists(svg) or os.path.getsize(svg) == 0:
                continue
            pdf = rm + ".pdf"
            cairosvg.svg2pdf(url=svg, write_to=pdf, background_color="white")
            writer.append(pdf)
        if len(writer.pages) == 0:
            return False
        os.makedirs(os.path.dirname(out_pdf), exist_ok=True)
        with open(out_pdf, "wb") as f:
            writer.write(f)
        return True
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser(description="Render handwritten notebooks to PDF (read-only on tablet).")
    ap.add_argument("dest", nargs="?", default=os.path.expanduser("~/remarkable_mirror"))
    ap.add_argument("--name", default=None, help="only notebooks whose name contains this (case-insensitive)")
    ap.add_argument("--force", action="store_true", help="re-render even if the output PDF exists")
    ap.add_argument("--list", action="store_true", help="list matching notebooks and exit")
    ap.add_argument("--host", default="10.11.99.1")
    args = ap.parse_args()

    nodes = load_nodes(args.host)
    # remote listing to tell pure notebooks (has .rm dir, no pdf/epub) apart
    remote = set(ssh(args.host, f"ls {DATA_DIR}").split())

    todo = []
    for uuid, n in nodes.items():
        if n.get("type") != "DocumentType" or n.get("deleted"):
            continue
        if f"{uuid}.pdf" in remote or f"{uuid}.epub" in remote:
            continue                      # annotated import, not a pure notebook
        if uuid not in remote:            # no page directory -> nothing to render
            continue
        rel = path_of(nodes, uuid)
        if rel is None:
            continue
        if args.name and args.name.lower() not in n["visibleName"].lower():
            continue
        out = os.path.join(args.dest, *rel[:-1], rel[-1] + ".pdf")
        todo.append((uuid, os.path.join(*rel), out))

    if args.list:
        for _, rel, _out in sorted(todo, key=lambda t: t[1]):
            print(rel)
        print(f"\n{len(todo)} notebook(s).")
        return

    print(f"==> rendering {len(todo)} notebook(s) to {args.dest}")
    ok = skip = fail = 0
    for uuid, rel, out in sorted(todo, key=lambda t: t[1]):
        if os.path.exists(out) and not args.force:
            skip += 1
            continue
        try:
            if render_notebook(args.host, uuid, out):
                ok += 1
                print(f"  + {rel}.pdf")
            else:
                fail += 1
                print(f"  ! {rel} (nothing rendered)")
        except Exception as e:              # noqa: BLE001 - keep going on one bad notebook
            fail += 1
            print(f"  ! {rel}: {e}")
    if not args.name:      # only a full run reflects the true totals
        write_state("render", {"done": ok, "present": skip, "failed": fail, "total": len(todo)})
    print(f"\n==> done: {ok} rendered, {skip} already present, {fail} failed")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as e:
        sys.exit(f"ERROR: command failed: {e}")
