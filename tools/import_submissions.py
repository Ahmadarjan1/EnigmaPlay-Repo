#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Import developer submissions approved in the EnigmaPlay developer portal into this repo.

For every approved submission:
  icons/<id>.png, screenshots/<id>/<n>.<ext>, files/<id>/<version>/<package files>,
  packages/<category>/<id>.json   -> validated with build_index.py --check, committed locally,
  then reported back to the API (imported / failed with a message for the developer).

Environment: EP_API (default the production API), SYNC_KEY (shared secret).
Run from the repo root by .github/workflows/import-submissions.yml (which pushes the commits).
"""
import datetime
import glob
import io
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
API = os.environ.get("EP_API", "https://enigmaplay-api.ahmadalarjan2.workers.dev").rstrip("/")
KEY = os.environ.get("SYNC_KEY", "")
MAX_URL_DOWNLOAD = 50 * 1024 * 1024
NAME_RE = re.compile(r"[^A-Za-z0-9._+-]")


def api(path, body=None, raw=False):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(API + path, data=data, method="POST" if data else "GET",
                                 headers={"X-Sync-Key": KEY, "Content-Type": "application/json",
                                          "User-Agent": "EnigmaPlay-import"})
    with urllib.request.urlopen(req, timeout=60) as r:
        out = r.read()
    return out if raw else json.loads(out.decode("utf-8"))


def download(url):
    req = urllib.request.Request(url, headers={"User-Agent": "EnigmaPlay-import"})
    with urllib.request.urlopen(req, timeout=120) as r:
        data = r.read(MAX_URL_DOWNLOAD + 1)
    if len(data) > MAX_URL_DOWNLOAD:
        raise ValueError("file larger than 50 MB: %s" % url)
    return data


def git(*args):
    return subprocess.run(["git"] + list(args), cwd=ROOT, check=True, capture_output=True, text=True).stdout


def rel(p):
    return os.path.relpath(p, ROOT).replace(os.sep, "/")


def write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def find_existing(pid):
    for p in glob.glob(os.path.join(ROOT, "packages", "*", pid + ".json")):
        return p
    return None


def import_one(s):
    pid, cat, ver = s["plugin_id"], s["category"], s["version"]
    meta = s.get("meta") or {}
    files = {f["name"]: f for f in s.get("files") or []}
    if not re.match(r"^[a-z0-9][a-z0-9-]{1,47}$", pid) or "/" in ver or ".." in ver:
        raise ValueError("bad id/version")

    old_path = find_existing(pid)
    old = {}
    if old_path:
        with io.open(old_path, encoding="utf-8") as f:
            old = json.load(f)

    def fetch(name):
        return api("/v1/sync/file/%d/%s" % (s["sid"], name), raw=True)

    # icon
    icon = old.get("icon")
    if "icon" in files:
        write(os.path.join(ROOT, "icons", pid + ".png"), fetch("icon"))
        icon = "icons/%s.png" % pid
    if not icon:
        raise ValueError("missing icon")

    # screenshots (a new set replaces the old one)
    shots = old.get("screenshots") or []
    new_shots = sorted([n for n in files if n.startswith("shot")], key=lambda n: int(n[4:]))
    if new_shots:
        sdir = os.path.join(ROOT, "screenshots", pid)
        if os.path.isdir(sdir):
            shutil.rmtree(sdir)
        shots = []
        for i, n in enumerate(new_shots, 1):
            ext = "jpg" if files[n]["mime"] == "image/jpeg" else "png"
            write(os.path.join(sdir, "%d.%s" % (i, ext)), fetch(n))
            shots.append("screenshots/%s/%d.%s" % (pid, i, ext))
    if not shots:
        raise ValueError("missing screenshots")

    # package files -> files/<id>/<version>/
    out_dir = os.path.join(ROOT, "files", pid, ver)
    downloads = []
    for kind in ("ipk", "deb", "sh"):
        data, fname = None, None
        if kind in files:
            data, fname = fetch(kind), files[kind]["filename"]
        elif meta.get("url_" + kind):
            url = meta["url_" + kind]
            data = download(url)
            fname = url.split("?")[0].rstrip("/").split("/")[-1]
        if data is None:
            continue
        if kind in ("ipk", "deb") and not data.startswith(b"!<arch>"):
            raise ValueError("%s is not a valid package" % kind)
        if kind == "sh" and not data.startswith(b"#!"):
            raise ValueError("sh file must start with #!")
        fname = NAME_RE.sub("_", fname or "") or "%s_%s.%s" % (pid, ver, kind)
        if not fname.endswith("." + kind):
            fname += "." + kind
        path = os.path.join(out_dir, fname)
        write(path, data)
        downloads.append({"type": kind, "file": rel(path)})
    if not downloads:
        raise ValueError("no package file")

    today = datetime.date.today().isoformat()
    changelog = list(old.get("changelog") or [])
    text = (meta.get("changelog") or "").strip() or ("أول إصدار" if not old else "")
    if text:
        changelog.insert(0, {"date": today, "text": "%s - %s" % (ver, text)})

    pkg = dict(old)
    pkg.update({
        "id": pid,
        "name": s["name"],
        "category": cat,
        "version": ver,
        "updated": today,
        "description": meta.get("description") or old.get("description", ""),
        "author": meta.get("author") or s.get("user"),
        "developer": s.get("user"),
        "python": meta.get("python") or ["3"],
        "restart": bool(meta.get("restart", True)),
        "icon": icon,
        "screenshots": shots,
        "downloads": downloads,
        "changelog": changelog[:20],
    })
    if meta.get("package"):
        pkg["package"] = meta["package"]
    if meta.get("description_en"):
        pkg.setdefault("i18n", {}).setdefault("en", {})["description"] = meta["description_en"]
    pkg.pop("sha256", None)

    new_path = os.path.join(ROOT, "packages", cat, pid + ".json")
    if old_path and os.path.abspath(old_path) != os.path.abspath(new_path):
        os.remove(old_path)
    os.makedirs(os.path.dirname(new_path), exist_ok=True)
    with io.open(new_path, "w", encoding="utf-8") as f:
        f.write(json.dumps(pkg, ensure_ascii=False, indent=2) + "\n")

    # validate the whole store with this plugin added
    chk = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "build_index.py"), "--check"],
                         cwd=ROOT, capture_output=True, text=True)
    if chk.returncode != 0:
        msgs = [l[6:] for l in chk.stdout.splitlines() if l.startswith("ERROR ")]
        raise ValueError("; ".join(msgs)[:400] or "validation failed")


def main():
    if not KEY:
        print("SYNC_KEY missing")
        sys.exit(1)
    subs = api("/v1/sync/approved").get("submissions", [])
    print("%d approved submission(s)" % len(subs))
    imported = 0
    for s in subs:
        label = "#%s %s %s" % (s["sid"], s["plugin_id"], s["version"])
        try:
            import_one(s)
            git("add", "-A")
            git("commit", "-q", "-m", "Import %s %s from developer %s" % (s["plugin_id"], s["version"], s.get("user")))
            api("/v1/sync/done", {"sid": s["sid"], "ok": True})
            imported += 1
            print("imported " + label)
        except Exception as e:
            git("reset", "-q", "--hard")
            git("clean", "-q", "-fd")
            msg = str(e)
            print("FAILED %s: %s" % (label, msg))
            try:
                api("/v1/sync/done", {"sid": s["sid"], "ok": False, "message": "فشل النشر: " + msg})
            except Exception as e2:
                print("  could not report: %s" % e2)
    print("imported %d" % imported)


if __name__ == "__main__":
    main()
