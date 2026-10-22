#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bring the categories edited by the admin (enigmaplay.org/site-admin, الأقسام) into this repo.

  GET  /v1/sync/categories        -> {rev, pending, categories: [...], moves: {plugin id: category}}
  categories.json is rewritten (one category per line, as before) and each moved plugin's manifest
  goes to packages/<category>/<id>.json with "category" set; the result is checked with
  build_index.py --check, committed, and reported:  POST /v1/sync/categories/done {rev, moved | error}

Environment: EP_API, SYNC_KEY (like import_submissions.py). Run by import-submissions.yml every
10 minutes, before the index is rebuilt; it does nothing when the admin changed nothing.
"""
import glob
import json
import os
import subprocess
import sys
import urllib.request

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
API = os.environ.get("EP_API", "https://enigmaplay.org").rstrip("/")
KEY = os.environ.get("SYNC_KEY", "")
FIELDS = ("id", "name", "name_en", "order", "color")


def api(path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(API + path, data=data, method="POST" if data else "GET",
                                 headers={"X-Sync-Key": KEY, "Content-Type": "application/json",
                                          "User-Agent": "EnigmaPlay-import"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def git(*args):
    subprocess.check_call(["git", "-C", ROOT] + list(args))


def write_categories(cats):
    """Same layout as the hand-written file: one category per line."""
    rows = []
    for c in cats:
        d = {k: c[k] for k in FIELDS if c.get(k) not in (None, "")}
        rows.append("  " + json.dumps(d, ensure_ascii=False))
    text = "[\n" + ",\n".join(rows) + "\n]\n"
    path = os.path.join(ROOT, "categories.json")
    old = open(path, encoding="utf-8").read() if os.path.exists(path) else ""
    if old != text:
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return True
    return False


def move_plugin(pid, cat):
    """packages/<old>/<id>.json -> packages/<cat>/<id>.json with "category": cat. True when moved."""
    found = [p for p in glob.glob(os.path.join(ROOT, "packages", "*", pid + ".json"))]
    if not found:
        return False
    src = found[0]
    text = open(src, encoding="utf-8").read()
    d = json.loads(text)
    dst = os.path.join(ROOT, "packages", cat, pid + ".json")
    if d.get("category") == cat and os.path.abspath(src) == os.path.abspath(dst):
        return True
    d["category"] = cat
    indent = 1 if text.startswith('{\n "') else 2
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.path.abspath(src) != os.path.abspath(dst):
        git("mv", os.path.relpath(src, ROOT), os.path.relpath(dst, ROOT))
    with open(dst, "w", encoding="utf-8") as f:
        f.write(json.dumps(d, ensure_ascii=False, indent=indent) + "\n")
    return True


def main():
    if not KEY:
        print("SYNC_KEY missing")
        sys.exit(1)
    st = api("/v1/sync/categories")
    if not st.get("pending"):
        print("categories: nothing changed")
        return
    rev, cats, moves = st.get("rev", 0), st.get("categories") or [], st.get("moves") or {}
    if not cats:
        print("categories: empty list, ignored")
        return
    try:
        changed = write_categories(cats)
        moved = [pid for pid, cat in sorted(moves.items()) if move_plugin(pid, cat)]
        subprocess.check_call([sys.executable, os.path.join(ROOT, "tools", "build_index.py"), "--check"])
        git("add", "-A", "categories.json", "packages")
        if subprocess.call(["git", "-C", ROOT, "diff", "--cached", "--quiet"]) != 0:
            git("commit", "-q", "-m", "Categories from the admin page (rev %d)" % rev)
        api("/v1/sync/categories/done", {"rev": rev, "moved": moved})
        print("categories rev %d: %s, %d plugin(s) moved" % (rev, "written" if changed else "unchanged", len(moved)))
    except Exception as e:
        git("reset", "-q", "--hard")
        print("categories FAILED: %s" % e)
        try:
            api("/v1/sync/categories/done", {"rev": rev, "error": str(e)[:300]})
        except Exception as e2:
            print("  could not report: %s" % e2)


if __name__ == "__main__":
    main()
