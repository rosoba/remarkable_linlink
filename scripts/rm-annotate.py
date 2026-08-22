#!/usr/bin/env python3
"""rm-annotate.py — export annotated PDFs (source + your ink) to PDF over USB/SSH.

Companion to rm-render.py (pure notebooks) and rm-pull.py (plain PDFs). For PDFs
you drew ON, this overlays the ink back onto the source page. reMarkable lets you
write in an *expandable canvas* beside the page, so the output uses a "page +
margins" canvas: the source page plus whatever margin area your ink occupies, so
nothing is clipped. Read-only on the tablet.

Shares the venv rm-render.py builds (rmc + rmscene + cairosvg + pypdf) and
re-execs into it.

Known limits (honest):
  - Text highlights (highlighter over the PDF's text = `GlyphRange` items) are
    NOT rendered by rmc — only pen/marker strokes come through.
  - Per-page zoom/pan is NOT applied. If you zoomed or panned a page while
    writing, that page's ink may be offset. The common case (write at default
    zoom, notes in the margin) aligns well.
  - For pixel-perfect fidelity incl. highlights, use reMarkable's own export.

Usage:  ./rm-annotate.py [dest_dir] [--name SUBSTR] [--force] [--list] [--host IP]
        Output goes to "<name> (annotated).pdf" in the mirror tree.
"""
import argparse
import glob
import io
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile

DATA_DIR = "/home/root/.local/share/remarkable/xochitl"
VENV = os.path.expanduser("~/.config/remarkable-linlink/rmvenv")
PKGS = ["rmc", "cairosvg", "pypdf"]
SCALE = 72.0 / 226.0          # rmc: points per reMarkable screen unit
PAGE_W_PT = 1404 * SCALE      # rM screen width in rmc points; PDFs fit to this
HALF = PAGE_W_PT / 2

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import remlink_index as idx  # noqa: E402


def patch_rmc_palette():
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
        return
    if not os.path.exists(py):
        print("==> first run: building render venv (rmc, cairosvg, pypdf)…")
        os.makedirs(os.path.dirname(VENV), exist_ok=True)
        subprocess.run([sys.executable, "-m", "venv", VENV], check=True)
        subprocess.run([py, "-m", "pip", "install", "-q", "--upgrade", "pip"], check=True)
        subprocess.run([py, "-m", "pip", "install", "-q", *PKGS], check=True)
        patch_rmc_palette()
    os.execv(py, [py, os.path.abspath(__file__), *sys.argv[1:]])


ensure_venv()
import cairosvg  # noqa: E402
from pypdf import PdfReader, PdfWriter, PageObject, Transformation  # noqa: E402


def ssh(host, cmd, binary=False):
    full = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", f"root@{host}", cmd]
    if binary:
        return subprocess.run(full, stdout=subprocess.PIPE, check=True).stdout
    return subprocess.run(full, capture_output=True, text=True, check=True).stdout


def sanitize(name):
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


def ink_svg_inner(venv_rmc, rm):
    """Render a .rm page to SVG; return (inner_xml, [vminx, vminy, vw, vh])."""
    svg = rm + ".svg"
    subprocess.run([venv_rmc, "-t", "svg", rm, "-o", svg], capture_output=True)
    if not os.path.exists(svg) or os.path.getsize(svg) == 0:
        return None, None
    raw = re.sub(r'<\?xml.*?\?>', '', open(svg).read(), flags=re.S)
    vb = re.search(r'viewBox="([-\d. ]+)"', raw)
    if not vb:
        return None, None
    inner = re.sub(r'<svg[^>]*>', '', raw, count=1, flags=re.S)
    inner = re.sub(r'</svg>\s*$', '', inner, flags=re.S)
    return inner, [float(x) for x in vb.group(1).split()]


def render_annotated(host, uuid, out_pdf):
    tmp = tempfile.mkdtemp(prefix="rmanno-")
    try:
        subprocess.run(["scp", "-q", f"root@{host}:{DATA_DIR}/{uuid}.pdf", tmp], check=True)
        subprocess.run(["scp", "-q", f"root@{host}:{DATA_DIR}/{uuid}.content", tmp], check=True)
        subprocess.run(["scp", "-q", "-r", f"root@{host}:{DATA_DIR}/{uuid}", tmp], check=True)
        base = PdfReader(os.path.join(tmp, f"{uuid}.pdf"))
        content = json.load(open(os.path.join(tmp, f"{uuid}.content")))
        order = [p["id"] for p in content.get("cPages", {}).get("pages", [])]
        have = {os.path.splitext(os.path.basename(p))[0]: p
                for p in glob.glob(os.path.join(tmp, uuid, "*.rm"))}
        rmc = os.path.join(VENV, "bin", "rmc")
        writer = PdfWriter()
        n_ink = 0
        for idx in range(len(base.pages)):
            bp = base.pages[idx]
            pid = order[idx] if idx < len(order) else None
            rm = have.get(pid) if pid else None
            inner = vb = None
            if rm:
                inner, vb = ink_svg_inner(rmc, rm)
            if not inner or not vb:
                writer.add_page(bp)          # no (renderable) ink -> page as-is
                continue
            pw = float(bp.mediabox.width); ph = float(bp.mediabox.height)
            s = pw / PAGE_W_PT; ph_rmc = ph / s
            vminx, vminy, vw, vh = vb
            cminx = min(-HALF, vminx); cmaxx = max(HALF, vminx + vw)
            cminy = min(0.0, vminy);   cmaxy = max(ph_rmc, vminy + vh)
            W = (cmaxx - cminx) * s; H = (cmaxy - cminy) * s
            wrapped = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
                       f'viewBox="0 0 {W} {H}"><g transform="translate({-cminx*s} {-cminy*s}) '
                       f'scale({s})">{inner}</g></svg>')
            open(rm + ".fit.svg", "w").write(wrapped)
            cairosvg.svg2pdf(url=rm + ".fit.svg", write_to=rm + ".ink.pdf")
            ink = PdfReader(rm + ".ink.pdf").pages[0]
            out = PageObject.create_blank_page(width=W, height=H)
            ox = (-HALF - cminx) * s; oy_top = (0 - cminy) * s
            out.merge_transformed_page(bp, Transformation().translate(ox, H - oy_top - ph))
            out.merge_page(ink)
            writer.add_page(out)
            n_ink += 1
        os.makedirs(os.path.dirname(out_pdf), exist_ok=True)
        part = out_pdf + ".part"          # write atomically so an interrupted run
        with open(part, "wb") as f:       # never leaves a partial PDF to be "adopted"
            writer.write(f)
        os.replace(part, out_pdf)
        return n_ink
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser(description="Export annotated PDFs (source + ink) to PDF.")
    ap.add_argument("dest", nargs="?", default=os.path.expanduser("~/remarkable_mirror"))
    ap.add_argument("--name", default=None, help="only docs whose name contains this (case-insensitive)")
    ap.add_argument("--force", action="store_true", help="re-export even if the output exists")
    ap.add_argument("--list", action="store_true", help="list matching annotated PDFs and exit")
    ap.add_argument("--host", default="10.11.99.1")
    args = ap.parse_args()

    nodes = load_nodes(args.host)
    remote = set(ssh(args.host, f"ls {DATA_DIR}").split())

    todo = []
    for uuid, n in nodes.items():
        if n.get("type") != "DocumentType" or n.get("deleted"):
            continue
        if f"{uuid}.pdf" not in remote or uuid not in remote:
            continue                      # need both a source PDF and an ink dir
        rel = path_of(nodes, uuid)
        if rel is None:
            continue
        if args.name and args.name.lower() not in n["visibleName"].lower():
            continue
        out = os.path.join(args.dest, *rel[:-1], rel[-1] + " (annotated).pdf")
        todo.append((uuid, os.path.join(*rel), out, n.get("lastModified"), rel[-1]))

    if args.list:
        for t in sorted(todo, key=lambda t: t[1]):
            print(t[1])
        print(f"\n{len(todo)} annotated PDF(s).")
        return

    con = idx.connect(args.dest)       # cache-index (change-detection + counts)
    print(f"==> exporting {len(todo)} annotated PDF(s) to {args.dest}")
    ok = skip = fail = 0
    for uuid, rel, out, mod, name in sorted(todo, key=lambda t: t[1]):
        if not args.force and idx.is_current(con, uuid, "annotated", out, mod):
            skip += 1
            idx.mark(con, uuid, "annotated", name, out, mod)   # record/adopt for counts
            continue
        try:
            n_ink = render_annotated(args.host, uuid, out)
            ok += 1
            idx.mark(con, uuid, "annotated", name, out, mod)
            print(f"  + {rel} (annotated).pdf  [{n_ink} inked page(s)]")
        except Exception as e:              # noqa: BLE001
            fail += 1
            print(f"  ! {rel}: {e}")
    print(f"\n==> done: {ok} exported, {skip} already present, {fail} failed")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as e:
        sys.exit(f"ERROR: command failed: {e}")
