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
import time
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


def raw_github(url):
    """github.com/<o>/<r>/blob/<branch>/<path> (the web page) -> raw.githubusercontent.com file."""
    m = re.match(r"^https://github\.com/([^/]+)/([^/]+)/(?:blob|raw)/(.+)$", url or "")
    return "https://raw.githubusercontent.com/%s/%s/%s" % m.groups() if m else url


def download(url):
    url = raw_github(url)
    req = urllib.request.Request(url, headers={"User-Agent": "EnigmaPlay-import"})
    with urllib.request.urlopen(req, timeout=120) as r:
        data = r.read(MAX_URL_DOWNLOAD + 1)
    if len(data) > MAX_URL_DOWNLOAD:
        raise ValueError("file larger than 50 MB: %s" % url)
    return data


# the store restarts the GUI itself after an install, so these are dropped from a developer's command
_RESTART_RE = re.compile(r"\s*(?:&&|;|\|\|)?\s*(?:killall\s+-9\s+enigma2|killall\s+enigma2|init\s+[346]|reboot|systemctl\s+restart\s+enigma2)\s*;?\s*$")


def script_from_telnet(cmd):
    """An install script made from the telnet command the developer gave (zip downloads, git clones...)."""
    cmd = " ".join((cmd or "").split())
    while True:
        new = _RESTART_RE.sub("", cmd)
        if new == cmd:
            break
        cmd = new
    if not cmd:
        raise ValueError("empty telnet command")
    return ("#!/bin/sh\n# Made by EnigmaPlay from the developer's telnet install command\nset -e\n%s\nexit 0\n" % cmd).encode("utf-8")


def fix_sh(data, fname, meta, pid, ver):
    """Accept small mistakes in an sh link: BOM / blank lines before #!, a script without #!.
    A link that is not a script at all (zip, web page) falls back to the telnet command."""
    d = data[3:] if data.startswith(b"\xef\xbb\xbf") else data
    d = d.lstrip()
    if d.startswith(b"#!"):
        return d, fname
    head = d[:4096]
    is_text = b"\0" not in head and not head.lower().startswith((b"<!doctype", b"<html"))
    if is_text and re.search(rb"(wget|curl|opkg|dpkg|apt|cp |mkdir|tar |unzip)", head):
        return b"#!/bin/sh\n" + d, fname
    if meta.get("telnet"):
        return script_from_telnet(meta["telnet"]), "%s_%s.sh" % (pid, ver)
    kind = "a zip file" if head.startswith(b"PK") else "a web page" if not is_text or head.lower().startswith((b"<!doctype", b"<html")) else "not a script"
    raise ValueError("the sh link is %s, not an install script (give the raw installer.sh link or a telnet command)" % kind)


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


def apply_edit(s):
    """An admin changed a plugin that is already in the store (لوحتي ← البلجنات ← تعديل).
    Only the fields that were sent change; the install files change only when a link was given."""
    pid, cat, ver = s["plugin_id"], s["category"], s["version"]
    meta = s.get("meta") or {}
    old_path = find_existing(pid)
    if not old_path:
        raise ValueError("plugin %s is not in the store" % pid)
    with io.open(old_path, encoding="utf-8") as f:
        pkg = json.load(f)
    old_ver = str(pkg.get("version", ""))
    # new icon / screenshots uploaded from the panel
    files = {f["name"]: f for f in s.get("files") or []}
    if "icon" in files:
        write(os.path.join(ROOT, "icons", pid + ".png"),
              api("/v1/sync/file/%d/%s" % (s["sid"], "icon"), raw=True))
        pkg["icon"] = "icons/%s.png" % pid
    new_shots = sorted([n for n in files if n.startswith("shot")], key=lambda n: int(n[4:]))
    if new_shots:
        sdir = os.path.join(ROOT, "screenshots", pid)
        if os.path.isdir(sdir):
            shutil.rmtree(sdir)
        shots = []
        for i, n in enumerate(new_shots, 1):
            ext = "jpg" if files[n]["mime"] == "image/jpeg" else "png"
            write(os.path.join(sdir, "%d.%s" % (i, ext)), api("/v1/sync/file/%d/%s" % (s["sid"], n), raw=True))
            shots.append("screenshots/%s/%d.%s" % (pid, i, ext))
        pkg["screenshots"] = shots
    pkg["name"] = s["name"]
    pkg["category"] = cat
    pkg["version"] = ver
    for k in ("description", "author", "homepage", "package"):
        if k in meta:
            if meta[k]:
                pkg[k] = meta[k]
            else:
                pkg.pop(k, None)
    if "python" in meta:
        pkg["python"] = meta["python"]
    if "restart" in meta:
        pkg["restart"] = bool(meta["restart"])
    if "telnet" in meta:
        if meta["telnet"]:
            pkg["telnet"] = " ".join(meta["telnet"].split())[:500]
        else:
            pkg.pop("telnet", None)
    if "description_en" in meta:
        if meta["description_en"]:
            pkg.setdefault("i18n", {}).setdefault("en", {})["description"] = meta["description_en"]
        else:
            (pkg.get("i18n") or {}).get("en", {}).pop("description", None)

    # install files: a new link replaces that type, "-" removes it, the others stay
    kinds = [k for k in ("ipk", "deb", "sh") if meta.get("url_" + k)]
    if kinds:
        keep = [d for d in pkg.get("downloads") or [] if d.get("type") not in kinds]
        out_dir = os.path.join(ROOT, "files", pid, ver)
        new = []
        for kind in kinds:
            url = meta["url_" + kind]
            if url == "-":
                continue
            data = download(url)
            fname = url.split("?")[0].rstrip("/").split("/")[-1]
            if kind == "sh":
                data, fname = fix_sh(data, fname, meta if meta.get("telnet") else dict(meta, telnet=pkg.get("telnet")), pid, ver)
            if kind in ("ipk", "deb") and not data.startswith(b"!<arch>"):
                raise ValueError("%s is not a valid package" % kind)
            fname = NAME_RE.sub("_", fname or "") or "%s_%s.%s" % (pid, ver, kind)
            if not fname.endswith("." + kind):
                fname += "." + kind
            path = os.path.join(out_dir, fname)
            write(path, data)
            new.append({"type": kind, "file": rel(path)})
        downloads = new + keep
        if not downloads and pkg.get("telnet"):
            path = os.path.join(out_dir, "%s_%s.sh" % (pid, ver))
            write(path, script_from_telnet(pkg["telnet"]))
            downloads = [{"type": "sh", "file": rel(path)}]
        if not downloads:
            raise ValueError("no install file left")
        order = {"ipk": 0, "deb": 1, "sh": 2}
        pkg["downloads"] = sorted(downloads, key=lambda d: order.get(d.get("type"), 9))
        pkg.pop("sha256", None)
        # links chosen by hand: the automatic update from the developer's source would undo them
        pkg.pop("source", None)

    # automatic updates from the developer's GitHub (set or switched off by the admin)
    src = meta.get("source")
    if src == "off":
        pkg.pop("source", None)
    elif isinstance(src, dict):
        pkg["source"] = src

    today = datetime.date.today().isoformat()
    if ver != old_ver or kinds:
        pkg["updated"] = today
        pkg["updated_at"] = int(time.time())
        text = (meta.get("changelog") or "").strip()
        if text or ver != old_ver:
            log = list(pkg.get("changelog") or [])
            log.insert(0, {"date": today, "text": "%s - %s" % (ver, text or "تحديث")})
            pkg["changelog"] = log[:20]

    new_path = os.path.join(ROOT, "packages", cat, pid + ".json")
    if os.path.abspath(old_path) != os.path.abspath(new_path):
        os.remove(old_path)
    os.makedirs(os.path.dirname(new_path), exist_ok=True)
    with io.open(new_path, "w", encoding="utf-8") as f:
        f.write(json.dumps(pkg, ensure_ascii=False, indent=2) + "\n")
    if isinstance(src, dict):
        # fetch from the new source now: a wrong repo / path fails here with a clear message
        sys.path.insert(0, os.path.join(ROOT, "tools"))
        import sync_sources
        sync_sources.ROOT = ROOT
        try:
            sync_sources.sync_one(new_path, False)
        except sync_sources.SourceError as e:
            raise ValueError("التحديث التلقائي: %s" % e)
    chk = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "build_index.py"), "--check"],
                         cwd=ROOT, capture_output=True, text=True)
    if chk.returncode != 0:
        msgs = [l[6:] for l in chk.stdout.splitlines() if l.startswith("ERROR ")]
        raise ValueError("; ".join(msgs)[:400] or "validation failed")


def import_one(s):
    if (s.get("meta") or {}).get("edit"):
        return apply_edit(s)
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
        if kind == "sh" and data is not None:
            data, fname = fix_sh(data, fname, meta, pid, ver)
        elif kind == "sh" and data is None and not downloads and meta.get("telnet"):
            # nothing to download: the developer only gave a telnet command
            data, fname = script_from_telnet(meta["telnet"]), "%s_%s.sh" % (pid, ver)
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
        "updated_at": int(time.time()),          # minute order inside the same day (latest additions)
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
    if (meta.get("telnet") or "").strip():
        pkg["telnet"] = " ".join(meta["telnet"].split())[:500]   # manual install command shown on the plugin page
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
            what = "Edit" if (s.get("meta") or {}).get("edit") else "Import"
            git("commit", "-q", "-m", "%s %s %s (%s)" % (what, s["plugin_id"], s["version"], s.get("user")))
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
