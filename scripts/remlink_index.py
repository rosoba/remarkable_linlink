"""Shared cache-index for the remarkable_linlink tools.

A small SQLite DB in the mirror root (``.remlink-index.db``) recording, per tablet
document, what has been pulled/rendered and the tablet ``lastModified`` it was made
from. This lets tools (a) redo work only when the tablet copy actually changed, and
(b) let remlink show accurate done/total counts.

It is a pure CACHE: delete the file and the tools fall back to filesystem
"skip if the output exists" rules; the next ``rm-pull`` rebuilds it. Every function
is best-effort — any DB error degrades to the filesystem behaviour rather than
breaking a tool.

kinds:  'pdf' (pulled original) · 'notebook' (rendered) · 'annotated' (rendered)
"""
import os
import sqlite3
import time

DB_NAME = ".remlink-index.db"


def path(mirror):
    return os.path.join(mirror, DB_NAME)


def connect(mirror):
    """Open (creating) the index; returns a connection or None on failure."""
    try:
        os.makedirs(mirror, exist_ok=True)
        con = sqlite3.connect(path(mirror), timeout=5)
        con.execute("PRAGMA journal_mode=WAL")
        con.execute(
            "CREATE TABLE IF NOT EXISTS items("
            "  uuid TEXT, kind TEXT, name TEXT, out_path TEXT,"
            "  src_modified INTEGER, processed_at INTEGER,"
            "  PRIMARY KEY(uuid, kind))")
        con.commit()
        return con
    except sqlite3.Error:
        return None


def _int(x):
    try:
        return int(x)
    except (TypeError, ValueError):
        return 0


def discover(con, uuid, kind, name, src_modified):
    """Record that a doc of this kind EXISTS (denominator) without marking it done."""
    if con is None:
        return
    try:
        con.execute(
            "INSERT INTO items(uuid,kind,name,src_modified,processed_at) "
            "VALUES(?,?,?,?,NULL) "
            "ON CONFLICT(uuid,kind) DO UPDATE SET name=excluded.name, "
            "  src_modified=excluded.src_modified",
            (uuid, kind, name, _int(src_modified)))
        con.commit()
    except sqlite3.Error:
        pass


def mark(con, uuid, kind, name, out_path, src_modified):
    """Mark a doc processed (pulled/rendered) at the given tablet lastModified."""
    if con is None:
        return
    try:
        con.execute(
            "INSERT INTO items(uuid,kind,name,out_path,src_modified,processed_at) "
            "VALUES(?,?,?,?,?,?) "
            "ON CONFLICT(uuid,kind) DO UPDATE SET name=excluded.name, "
            "  out_path=excluded.out_path, src_modified=excluded.src_modified, "
            "  processed_at=excluded.processed_at",
            (uuid, kind, name, out_path, _int(src_modified), int(time.time())))
        con.commit()
    except sqlite3.Error:
        pass


def is_current(con, uuid, kind, out_path, src_modified):
    """True => output is up to date (skip). False => (re)process.

    Rules: no output file -> process. Output exists but not recorded as done
    (fresh index, or a pre-index render) -> adopt it (skip; the caller then marks
    it). Recorded done -> skip only if the recorded tablet lastModified is >= the
    current one, so a tablet edit triggers a re-render."""
    if not os.path.exists(out_path):
        return False
    if con is None:
        return True                        # output exists, no index -> filesystem rule
    try:
        row = con.execute(
            "SELECT src_modified, processed_at FROM items WHERE uuid=? AND kind=?",
            (uuid, kind)).fetchone()
    except sqlite3.Error:
        return True
    if not row or row[1] is None:
        return True                        # adopt a pre-existing output (caller marks it)
    return _int(row[0]) >= _int(src_modified)


def prune(con, kind, keep_uuids):
    """Drop rows of `kind` whose uuid is no longer present on the tablet."""
    if con is None:
        return
    try:
        stale = [u for (u,) in con.execute(
            "SELECT uuid FROM items WHERE kind=?", (kind,)).fetchall()
            if u not in keep_uuids]
        con.executemany("DELETE FROM items WHERE uuid=? AND kind=?",
                        [(u, kind) for u in stale])
        con.commit()
    except sqlite3.Error:
        pass


def counts(mirror):
    """For remlink: {kind: (done, total)} or None if no usable index."""
    p = path(mirror)
    if not os.path.exists(p):
        return None
    try:
        con = sqlite3.connect(p, timeout=5)
        out = {}
        for kind in ("pdf", "notebook", "annotated"):
            total = con.execute("SELECT COUNT(*) FROM items WHERE kind=?",
                                (kind,)).fetchone()[0]
            done = con.execute(
                "SELECT COUNT(*) FROM items WHERE kind=? AND processed_at IS NOT NULL",
                (kind,)).fetchone()[0]
            out[kind] = (done, total)
        con.close()
        return out
    except sqlite3.Error:
        return None
