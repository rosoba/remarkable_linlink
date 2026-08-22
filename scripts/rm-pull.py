#!/usr/bin/env python3
"""rm-pull.py — mirror the reMarkable library to a local folder over USB/SSH.

ONE-WAY, tablet -> local, read-only on the tablet (safe: it never writes to or
deletes anything on the device). Reconstructs the real folder/name hierarchy
from each document's .metadata (the on-device store is a flat pile of UUIDs;
folders are virtual via the `parent` field) and copies the *original* PDFs/EPUBs.

Handwritten notebooks are stored in reMarkable's .rm lines format (not PDF) and
are NOT exported here — they are listed in `_notebooks-not-exported.txt` at the
destination. Exporting those needs a renderer that supports the Paper Pro format.

Usage:  ./rm-pull.py [dest_dir] [--host 10.11.99.1]
        dest_dir defaults to ./remarkable-mirror
"""
import argparse
import io
import json
import os
import re
import subprocess
import sys
import tarfile

DATA_DIR = "/home/root/.local/share/remarkable/xochitl"


def ssh(host, cmd, capture=True, binary=False):
    full = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
            f"root@{host}", cmd]
    if binary:
        return subprocess.run(full, stdout=subprocess.PIPE, check=True).stdout
    return subprocess.run(full, capture_output=capture, text=True, check=True).stdout


def sanitize(name):
    name = name.strip() or "(unnamed)"
    name = re.sub(r'[\x00-\x1f/\\]', "_", name)   # no slashes / control chars
    return name[:150]


def main():
    ap = argparse.ArgumentParser(description="Mirror reMarkable library to a local folder (one-way, read-only on tablet).")
    ap.add_argument("dest", nargs="?", default="remarkable-mirror", help="destination directory")
    ap.add_argument("--host", default="10.11.99.1")
    args = ap.parse_args()

    print(f"==> pulling from root@{args.host}:{DATA_DIR}")

    # 1. Remote file listing with sizes (single ssh) -> {name: size}
    listing = ssh(args.host, f"cd {DATA_DIR} && ls -la")
    sizes = {}
    for line in listing.splitlines():
        parts = line.split(None, 8)
        if len(parts) == 9 and not parts[0].startswith("d"):
            sizes[parts[8]] = int(parts[4])

    # 2. All .metadata files in one tar stream (small; single ssh)
    tar_bytes = ssh(args.host, f"cd {DATA_DIR} && tar cf - *.metadata", binary=True)
    nodes = {}
    with tarfile.open(fileobj=io.BytesIO(tar_bytes)) as tf:
        for m in tf.getmembers():
            uuid = m.name[:-len(".metadata")]
            f = tf.extractfile(m)
            if f is None:
                continue
            try:
                meta = json.loads(f.read().decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                print(f"  ! skipping unreadable metadata: {m.name}", file=sys.stderr)
                continue
            nodes[uuid] = meta

    # 3. Resolve each node's folder path (walk parents), skipping trash/deleted
    def path_of(uuid, _seen=None):
        _seen = _seen or set()
        if uuid in ("", "trash") or uuid in _seen:
            return None if uuid == "trash" else []
        n = nodes.get(uuid)
        if not n or n.get("deleted"):
            return None
        _seen.add(uuid)
        parent = path_of(n.get("parent", ""), _seen)
        if parent is None:
            return None
        return parent + [sanitize(n["visibleName"])]

    docs, notebooks = [], []
    for uuid, n in nodes.items():
        if n.get("type") != "DocumentType" or n.get("deleted"):
            continue
        rel = path_of(uuid)
        if rel is None:            # in trash or under a deleted/trashed folder
            continue
        ext = "pdf" if f"{uuid}.pdf" in sizes else ("epub" if f"{uuid}.epub" in sizes else None)
        if ext:
            docs.append((uuid, ext, os.path.join(*rel[:-1]) if len(rel) > 1 else "", rel[-1]))
        else:
            notebooks.append(os.path.join(*rel))

    # 4. Copy originals, skipping unchanged (same size) files
    os.makedirs(args.dest, exist_ok=True)
    copied = skipped = 0
    for uuid, ext, folder, name in docs:
        outdir = os.path.join(args.dest, folder)
        os.makedirs(outdir, exist_ok=True)
        target = os.path.join(outdir, f"{name}.{ext}")
        remote = f"{uuid}.{ext}"
        if os.path.exists(target) and os.path.getsize(target) == sizes.get(remote):
            skipped += 1
            continue
        subprocess.run(["scp", "-q", f"root@{args.host}:{DATA_DIR}/{remote}", target], check=True)
        copied += 1
        print(f"  + {os.path.join(folder, name)}.{ext}")

    # 5. Record notebooks we couldn't export
    if notebooks:
        with open(os.path.join(args.dest, "_notebooks-not-exported.txt"), "w") as f:
            f.write("Handwritten notebooks (no PDF/EPUB original) — not exported:\n\n")
            f.write("\n".join(sorted(notebooks)) + "\n")

    print(f"\n==> done: {copied} copied, {skipped} unchanged, "
          f"{len(notebooks)} notebooks skipped (see _notebooks-not-exported.txt)")
    print(f"    mirror at: {os.path.abspath(args.dest)}")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as e:
        sys.exit(f"ERROR: command failed: {e}")
