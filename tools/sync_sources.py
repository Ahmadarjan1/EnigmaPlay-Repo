#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Follow plugins that are published by their author in another GitHub repository.

A manifest in packages/<category>/<id>.json may carry a "source" block:

  Files kept in the author's repo (most Enigma2 plugins: installer.sh + a version file):
    "source": {
      "repo": "biko-73/AjPanel",            # GitHub owner/repo (github.com only)
      "branch": "main",                     # optional, default: the repo's default branch
      "files": [{"type": "sh", "path": "installer.sh"}],
      "version_file": "version",            # file in the repo that holds the version
      "version_regex": "version=([0-9][\\w.\\-]*)"   # optional; default: first x.y[.z...]
    }

  GitHub Releases (the latest release; version = tag without a leading "v"):
    "source": {
      "repo": "owner/name",
      "release": true,
      "assets": [{"type": "ipk", "match": "_all\\.ipk$"}, {"type": "deb", "match": "\\.deb$"}]
    }

When the upstream version differs from the manifest (or a mirrored file changed), the files are
copied into files/<id>/<version>/, the manifest's version / downloads / updated / changelog are
updated and the previous mirrored version folder is removed. The store keeps serving its own
copies, so the signed index still pins every file by sha256.

Usage: python3 tools/sync_sources.py [--only <id>] [--dry-run]
Env:   GITHUB_TOKEN (optional, raises the API rate limit)
Exit:  0 always unless the script itself is broken; problems with one plugin are reported and skipped.
"""
import argparse
import datetime
import glob
import hashlib
import io
import json
import os
import re
import shutil
import sys
import urllib.request
import urllib.error

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
PATH_RE = re.compile(r"^[A-Za-z0-9_.\-/ ]+$")
TYPES = ("ipk", "deb", "sh")
MAX_FILE = 60 * 1024 * 1024
DEFAULT_VER_RE = r"([0-9]+(?:\.[0-9A-Za-z]+)+)"


class SourceError(Exception):
    pass


def http_get(url, binary=True, api=False):
    headers = {"User-Agent": "EnigmaPlay-sync"}
    tok = os.environ.get("GITHUB_TOKEN")
    if tok and (api or url.startswith("https://api.github.com/")):
        headers["Authorization"] = "Bearer " + tok
    if api:
        headers["Accept"] = "application/vnd.github+json"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data = r.read(MAX_FILE + 1)
    except urllib.error.HTTPError as e:
        raise SourceError("%s -> HTTP %s" % (url, e.code))
    except Exception as e:
        raise SourceError("%s -> %s" % (url, e))
    if len(data) > MAX_FILE:
        raise SourceError("%s is larger than %d MB" % (url, MAX_FILE // 1048576))
    return data if binary else data.decode("utf-8", "replace")


def api(path):
    return json.loads(http_get("https://api.github.com" + path, api=True).decode("utf-8"))


def check_payload(kind, name, data):
    if kind in ("ipk", "deb"):
        if not data.startswith(b"!<arch>") and not data[:2] == b"\x1f\x8b":
            raise SourceError("%s is not a valid .%s package" % (name, kind))
    elif kind == "sh":
        head = data[:200].lstrip()
        if b"\x00" in data[:4096] or not (head.startswith(b"#!") or head.startswith(b"#")):
            raise SourceError("%s does not look like a shell script" % name)


def safe_name(name):
    name = os.path.basename(name)
    if not name or name.startswith(".") or not PATH_RE.match(name):
        raise SourceError("unsafe file name %r" % name)
    return name


def safe_version(v):
    v = (v or "").strip()
    if v[:1] in ("v", "V") and v[1:2].isdigit():
        v = v[1:]
    if not re.match(r"^[0-9A-Za-z][0-9A-Za-z.\-_+ ]{0,31}$", v):
        raise SourceError("unusable version %r" % v)
    return v


def upstream(src):
    """-> (version, [(type, filename, bytes)], release_notes)"""
    repo = src.get("repo", "")
    if not REPO_RE.match(repo):
        raise SourceError("source.repo must be owner/name, got %r" % repo)
    if src.get("release"):
        rel = api("/repos/%s/releases/latest" % repo)
        version = safe_version(rel.get("tag_name") or rel.get("name"))
        out = []
        for spec in src.get("assets") or []:
            kind, pat = spec.get("type"), spec.get("match", "")
            if kind not in TYPES:
                raise SourceError("asset type must be one of %s" % (TYPES,))
            hit = [a for a in rel.get("assets", []) if re.search(pat, a.get("name", ""))]
            if not hit:
                raise SourceError("no release asset matches %r in %s %s" % (pat, repo, rel.get("tag_name")))
            a = hit[0]
            data = http_get(a["browser_download_url"])
            name = safe_name(a["name"])
            check_payload(kind, name, data)
            out.append((kind, name, data))
        if not out:
            raise SourceError("source.assets is empty")
        notes = (rel.get("body") or "").strip().splitlines()
        return version, out, (notes[0][:140] if notes else "")
    branch = src.get("branch") or api("/repos/%s" % repo).get("default_branch", "main")
    raw = "https://raw.githubusercontent.com/%s/%s/" % (repo, branch)
    vf = src.get("version_file", "")
    if not vf or not PATH_RE.match(vf) or ".." in vf:
        raise SourceError("source.version_file is required")
    text = http_get(raw + vf.lstrip("/"), binary=False)
    m = re.search(src.get("version_regex") or DEFAULT_VER_RE, text)
    if not m:
        raise SourceError("version not found in %s/%s" % (repo, vf))
    version = safe_version(m.group(1))
    out = []
    for spec in src.get("files") or []:
        kind, path = spec.get("type"), spec.get("path", "")
        if kind not in TYPES or not PATH_RE.match(path) or ".." in path:
            raise SourceError("bad source file entry %r" % (spec,))
        data = http_get(raw + path.lstrip("/"))
        name = safe_name(path)
        check_payload(kind, name, data)
        out.append((kind, name, data))
    if not out:
        raise SourceError("source.files is empty")
    return version, out, ""


def sha(b):
    return hashlib.sha256(b).hexdigest()


def sync_one(path, dry):
    with io.open(path, encoding="utf-8") as f:
        m = json.load(f)
    src = m.get("source")
    pid = m.get("id") or os.path.basename(path)[:-5].lstrip("_")
    version, files, notes = upstream(src)
    new_dir = "files/%s/%s" % (pid, version)
    wanted = [{"type": k, "file": "%s/%s" % (new_dir, n)} for k, n, _ in files]
    same_version = (m.get("version") == version)
    changed_files = []
    for (k, n, data), d in zip(files, wanted):
        p = os.path.join(ROOT, d["file"])
        if not os.path.isfile(p) or sha(open(p, "rb").read()) != sha(data):
            changed_files.append((p, data))
    same_downloads = [(d.get("type"), d.get("file")) for d in m.get("downloads", [])] == \
                     [(d["type"], d["file"]) for d in wanted]
    if same_version and same_downloads and not changed_files:
        return None
    what = "%s %s" % (pid, version) if not same_version else "%s %s (files updated)" % (pid, version)
    if dry:
        return what + " [dry run]"
    for p, data in changed_files:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(data)
    old_dirs = set(os.path.dirname(d.get("file", "")) for d in m.get("downloads", []))
    today = datetime.date.today().isoformat()
    m["downloads"] = wanted
    m["updated"] = today
    if not same_version:
        old = m.get("version")
        m["version"] = version
        text = "%s - %s" % (version, notes or "تحديث تلقائي من مصدر المطوّر (%s)" % src["repo"])
        m["changelog"] = [{"date": today, "text": text}] + list(m.get("changelog") or [])[:19]
        print("  %s: %s -> %s" % (pid, old, version))
    with io.open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps(m, ensure_ascii=False, indent=2) + "\n")
    # drop the previously mirrored version folder (only folders under files/<id>/ that are no longer used)
    for d in old_dirs:
        if d and d != new_dir and d.startswith("files/%s/" % pid) and d.count("/") == 2:
            full = os.path.join(ROOT, d)
            if os.path.isdir(full):
                shutil.rmtree(full)
    return what


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    done, failed = [], []
    for path in sorted(glob.glob(os.path.join(ROOT, "packages", "*", "*.json"))):
        try:
            with io.open(path, encoding="utf-8") as f:
                m = json.load(f)
        except Exception:
            continue
        if not isinstance(m, dict) or not m.get("source"):
            continue
        if a.only and m.get("id") != a.only:
            continue
        try:
            r = sync_one(path, a.dry_run)
            print("%-24s %s" % (m.get("id"), r or "up to date"))
            if os.environ.get("GITHUB_ACTIONS"):
                print("::notice title=sync %s::%s" % (m.get("id"), r or "up to date (%s)" % m.get("version")))
            if r:
                done.append(r)
        except SourceError as e:
            print("%-24s ERROR %s" % (m.get("id"), e))
            if os.environ.get("GITHUB_ACTIONS"):
                print("::warning title=sync %s::%s" % (m.get("id"), e))
            failed.append("%s: %s" % (m.get("id"), e))
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a") as f:
            f.write("changed=%s\n" % ("1" if done else "0"))
            f.write("message=Sync: %s\n" % ", ".join(done)[:200])
    if failed:
        print("\n%d source(s) failed:\n  %s" % (len(failed), "\n  ".join(failed)))


if __name__ == "__main__":
    main()
