#!/usr/bin/env python3
"""rm-push.py — upload a PDF (or EPUB) onto the reMarkable over USB/SSH.

ADD-ONLY: it creates a new document with a fresh UUID and the metadata the
tablet needs; it never modifies or deletes existing documents. After copying it
reloads xochitl so the new file appears in the library.

Usage:  ./rm-push.py FILE.pdf [-f "Folder Name"] [--host 10.11.99.1]
        -f/--folder  put it in a top-level folder of that name (created if absent)
                     omit to place it at the library root.
"""
import argparse
import json
import os
import subprocess
import sys
import time
import uuid as uuidlib

DATA_DIR = "/home/root/.local/share/remarkable/xochitl"


def ssh(host, cmd):
    return subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
                           f"root@{host}", cmd], capture_output=True, text=True, check=True).stdout


def scp(host, local, remote):
    subprocess.run(["scp", "-q", local, f"root@{host}:{DATA_DIR}/{remote}"], check=True)


def pdf_pagecount(path):
    try:
        out = subprocess.run(["pdfinfo", path], capture_output=True, text=True).stdout
        for line in out.splitlines():
            if line.startswith("Pages:"):
                return int(line.split()[1])
    except Exception:
        pass
    return 0


def find_or_make_folder(host, name, tmp):
    """Return the UUID of a top-level CollectionType named `name`, creating it if needed."""
    # scan existing metadata for a matching, non-deleted, root-level collection
    listing = ssh(host, f"cd {DATA_DIR} && grep -l '\"visibleName\": \"{name}\"' *.metadata 2>/dev/null || true")
    for fn in listing.split():
        meta = json.loads(ssh(host, f"cat {DATA_DIR}/{fn}"))
        if (meta.get("type") == "CollectionType" and not meta.get("deleted")
                and meta.get("visibleName") == name and meta.get("parent") in ("", None)):
            return fn[:-len(".metadata")]
    # create it
    fuid = str(uuidlib.uuid4())
    now = str(int(time.time() * 1000))
    meta = {"createdTime": now, "deleted": False, "lastModified": now,
            "lastOpened": "", "metadatamodified": False, "modified": False,
            "parent": "", "pinned": False, "synced": False,
            "type": "CollectionType", "version": 0, "visibleName": name}
    mpath = os.path.join(tmp, f"{fuid}.metadata")
    cpath = os.path.join(tmp, f"{fuid}.content")
    open(mpath, "w").write(json.dumps(meta, indent=4))
    open(cpath, "w").write("{}")
    scp(host, mpath, f"{fuid}.metadata")
    scp(host, cpath, f"{fuid}.content")
    print(f"  created folder '{name}'")
    return fuid


def main():
    ap = argparse.ArgumentParser(description="Upload a PDF/EPUB to the reMarkable (add-only).")
    ap.add_argument("file")
    ap.add_argument("-f", "--folder", default=None, help="top-level folder name (created if absent)")
    ap.add_argument("--host", default="10.11.99.1")
    args = ap.parse_args()

    if not os.path.isfile(args.file):
        sys.exit(f"ERROR: no such file: {args.file}")
    ext = os.path.splitext(args.file)[1].lower().lstrip(".")
    if ext not in ("pdf", "epub"):
        sys.exit("ERROR: only .pdf or .epub are supported")

    name = os.path.splitext(os.path.basename(args.file))[0]
    docid = str(uuidlib.uuid4())
    now = str(int(time.time() * 1000))

    import tempfile
    tmp = tempfile.mkdtemp(prefix="rmpush-")

    parent = ""
    if args.folder:
        parent = find_or_make_folder(args.host, args.folder, tmp)

    meta = {"createdTime": now, "deleted": False, "lastModified": now,
            "lastOpened": now, "lastOpenedPage": 0, "metadatamodified": False,
            "modified": False, "parent": parent, "pinned": False, "synced": False,
            "type": "DocumentType", "version": 0, "visibleName": name}

    content = {"extraMetadata": {}, "fileType": ext, "fontName": "",
               "lastOpenedPage": 0, "lineHeight": -1, "margins": 100,
               "orientation": "portrait", "pageCount": pdf_pagecount(args.file) if ext == "pdf" else 0,
               "textScale": 1,
               "transform": {"m11": 1, "m12": 0, "m13": 0, "m21": 0, "m22": 1,
                             "m23": 0, "m31": 0, "m32": 0, "m33": 1}}

    open(os.path.join(tmp, f"{docid}.metadata"), "w").write(json.dumps(meta, indent=4))
    open(os.path.join(tmp, f"{docid}.content"), "w").write(json.dumps(content, indent=4))

    print(f"==> uploading '{name}' ({ext}) to root@{args.host}"
          + (f" in folder '{args.folder}'" if args.folder else " (root)"))
    scp(args.host, args.file, f"{docid}.{ext}")
    scp(args.host, os.path.join(tmp, f"{docid}.metadata"), f"{docid}.metadata")
    scp(args.host, os.path.join(tmp, f"{docid}.content"), f"{docid}.content")

    print("  reloading xochitl…")
    ssh(args.host, "systemctl restart xochitl")
    print(f"==> done. New document UUID: {docid}")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as e:
        sys.exit(f"ERROR: command failed: {e.stderr or e}")
