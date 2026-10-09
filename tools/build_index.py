#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EnigmaPlay-Repo index builder
=============================
Reads   categories.json + packages/**/*.json
Writes  index.json  (the single file the EnigmaPlay plugin downloads)

For every download it fills in sha256 + size automatically:
  * files stored in this repo (files/...)  -> hashed from disk
  * any https URL (Releases, raw, ...)     -> downloaded once and hashed
Set "sha256": "skip" on a download to leave it unverified (e.g. a 3rd-party
script that changes every day).

Usage:  python3 tools/build_index.py [--offline] [--check]
  --offline  do not download remote files (keeps sha256 from the previous index.json)
  --check    validate only, do not write index.json (exit 1 on errors)
"""
from __future__ import print_function

import datetime
import hashlib
import io
import json
import os
import re
import sys
import urllib.request

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OWNER_REPO = os.environ.get("GITHUB_REPOSITORY", "Ahmadarjan1/EnigmaPlay-Repo")
BRANCH = os.environ.get("INDEX_BRANCH", "main")
RAW_BASE = "https://raw.githubusercontent.com/%s/%s/" % (OWNER_REPO, BRANCH)

SCHEMA = 2
ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,63}$")
TYPES = ("ipk", "deb", "sh")
PY_VALUES = ("2", "3")
MAX_DOWNLOAD = 200 * 1024 * 1024
ALLOWED_HOSTS = ("raw.githubusercontent.com", "github.com")

MIN_SCREENSHOTS = 1
MAX_SHOT_KB = 3 * 1024
IMG_EXT = (".png", ".jpg", ".jpeg")

errors = []
warnings = []


def err(where, msg):
    errors.append("%s: %s" % (where, msg))


def warn(where, msg):
    warnings.append("%s: %s" % (where, msg))


def check_image(where, path, what, max_kb):
    if not path.lower().endswith(IMG_EXT):
        err(where, "%s must be PNG or JPG: %s" % (what, os.path.basename(path)))
        return
    with open(path, "rb") as f:
        head = f.read(8)
    if not (head.startswith(b"\x89PNG") or head.startswith(b"\xff\xd8")):
        err(where, "%s is not a real PNG/JPG file: %s" % (what, os.path.basename(path)))
    kb = os.path.getsize(path) // 1024
    if kb > max_kb:
        err(where, "%s too large (%d KB, max %d KB): %s" % (what, kb, max_kb, os.path.basename(path)))


def load_json(path):
    with io.open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest(), os.path.getsize(path)


def sha256_url(url):
    req = urllib.request.Request(url, headers={"User-Agent": "EnigmaPlay-IndexBuilder/1.0"})
    h = hashlib.sha256()
    size = 0
    with urllib.request.urlopen(req, timeout=60) as resp:
        while True:
            chunk = resp.read(1 << 16)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_DOWNLOAD:
                raise ValueError("file larger than %d MB" % (MAX_DOWNLOAD // (1024 * 1024)))
            h.update(chunk)
    return h.hexdigest(), size


GH_RAW_BASE = RAW_BASE.replace("https://raw.githubusercontent.com/", "https://github.com/").replace("/main/", "/raw/main/")


def resolve_repo_path(rel):
    """'files/x.sh' or 'icons/x.png' (stored in this repo) -> (abs_path, raw_url)."""
    rel = rel.lstrip("/")
    return os.path.join(ROOT, rel), RAW_BASE + rel


def previous_hashes():
    """url -> (sha256, size) from the last index.json, used by --offline and as a cache."""
    out = {}
    p = os.path.join(ROOT, "index.json")
    if os.path.isfile(p):
        try:
            for it in load_json(p).get("items", []):
                for d in it.get("downloads", []):
                    if d.get("url") and d.get("sha256"):
                        out[d["url"]] = (d["sha256"], d.get("size", 0))
        except Exception:
            pass
    return out


def norm_date(v, where):
    if not v:
        return None
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.datetime.strptime(str(v), fmt).strftime("%d.%m.%Y")
        except ValueError:
            continue
    err(where, "bad date %r (use YYYY-MM-DD)" % v)
    return None


KEEP_ALWAYS = ("id", "category", "name", "version", "description", "url", "downloads", "python")
DEFAULTS = {"line_no": 0, "order": 1000, "host": "other", "dangerous": False, "restart": False, "featured": False}


def slim(it):
    """Drop empty / default fields: every reader (box Item.from_dict, web page) has the same defaults.
    The index got ~3x bigger with hundreds of items; most of it was nulls and empty lists."""
    out = {}
    for k, v in it.items():
        if k in KEEP_ALWAYS:
            out[k] = v
        elif v is None or v == [] or v == {} or v == "" or (k in DEFAULTS and v == DEFAULTS[k]):
            continue
        else:
            out[k] = v
    out["downloads"] = [{k: v for k, v in d.items() if not (v is None or (k == "size" and not v))}
                        for d in it.get("downloads") or []]
    return out


# ---- backup sources (tools/mirror_sources.py writes mirror/map.json) ----
_MIRROR_MAP = None


def mirror_map():
    global _MIRROR_MAP
    if _MIRROR_MAP is None:
        p = os.path.join(ROOT, "mirror", "map.json")
        try:
            with open(p, encoding="utf-8") as f:
                _MIRROR_MAP = json.load(f).get("items", {})
        except Exception:
            _MIRROR_MAP = {}
    return _MIRROR_MAP


def with_mirrors(entry):
    """-> list of download entries. Adds "mirrors" (tried by the plugin when the link fails);
    a dead link is replaced by its mirror, or by the alternative packages when there is no mirror."""
    e = mirror_map().get(entry.get("url"))
    if not e:
        return [entry]
    own = entry.pop("mirrors", [])
    backups = list(own)
    if e.get("mirror"):
        backups.append({"type": entry["type"], "url": e["mirror"]})
    for a in e.get("alt") or []:
        if a.get("url") and a.get("type") in TYPES:
            backups.append({"type": a["type"], "url": a["url"]})
    if e.get("alive", True) or not backups:
        if backups:
            entry["mirrors"] = backups[:6]
        return [entry]
    if e.get("mirror"):
        new = dict(entry, url=e["mirror"], sha256=None, size=0)
        rest = [b for b in backups if b["url"] != e["mirror"]]
        if rest:
            new["mirrors"] = rest[:6]
        else:
            new.pop("mirrors", None)
        return [new]
    # no mirror: the alternatives become the downloads (the box picks ipk / deb for its package manager)
    out, seen = [], set()
    for b in backups:
        if b["type"] in seen and b["type"] != "sh":
            continue
        seen.add(b["type"])
        out.append({"type": b["type"], "url": b["url"], "sha256": None, "size": 0})
    return out


def source_page(url):
    """Repository page of the developer a download comes from (credit shown on the plugin page)."""
    u = url or ""
    m = re.match(r"https://raw\.githubusercontent\.com/([^/]+)/([^/]+)/", u) or \
        re.match(r"https://github\.com/([^/]+)/([^/]+)/(?:raw|releases|blob|archive)/", u)
    if m and m.group(1).lower() != OWNER_REPO.split("/")[0].lower():
        return "https://github.com/%s/%s" % (m.group(1), m.group(2))
    m = re.match(r"https://gitlab\.com/([^/]+)/([^/]+)/", u)
    if m:
        return "https://gitlab.com/%s/%s" % (m.group(1), m.group(2))
    return None


def build(offline=False):
    cats = load_json(os.path.join(ROOT, "categories.json"))
    cat_ids = set()
    for c in cats:
        if not c.get("id") or not c.get("name"):
            err("categories.json", "each category needs id + name: %r" % c)
        cat_ids.add(c.get("id"))
    cats.sort(key=lambda c: (c.get("order", 999), c.get("id", "")))

    prev = previous_hashes()
    items = []
    seen = set()
    pkg_dir = os.path.join(ROOT, "packages")
    for dirpath, _, files in os.walk(pkg_dir):
        for fn in sorted(files):
            if not fn.endswith(".json") or fn.startswith("_"):
                continue
            path = os.path.join(dirpath, fn)
            where = os.path.relpath(path, ROOT)
            try:
                p = load_json(path)
            except Exception as e:
                err(where, "invalid JSON: %s" % e)
                continue

            pid = p.get("id") or fn[:-5]
            if not ID_RE.match(pid):
                err(where, "id %r must be lowercase letters/digits/._-" % pid)
            if pid in seen:
                err(where, "duplicate id %r" % pid)
            seen.add(pid)

            for req in ("name", "category", "version"):
                if not p.get(req):
                    err(where, "missing %r" % req)
            if p.get("category") and p["category"] not in cat_ids:
                err(where, "unknown category %r (add it to categories.json)" % p["category"])

            py = [str(x) for x in p.get("python", ["2", "3"])]
            if any(x not in PY_VALUES for x in py):
                err(where, "python must be a list of \"2\"/\"3\"")

            downloads = []
            raw_dl = p.get("downloads")
            if not raw_dl:
                err(where, "needs at least one entry in \"downloads\"")
                raw_dl = []
            for i, d in enumerate(raw_dl):
                dw = "%s downloads[%d]" % (where, i)
                dtype = d.get("type")
                if dtype not in TYPES:
                    err(dw, "type must be one of %s" % (TYPES,))
                    continue
                url, local = d.get("url"), None
                if d.get("file"):
                    local, url = resolve_repo_path(d["file"])
                    if not os.path.isfile(local):
                        err(dw, "file not found in repo: %s" % d["file"])
                        continue
                if not url or not url.startswith("https://"):
                    err(dw, "needs https \"url\" or repo \"file\"")
                    continue
                host = re.sub(r"^https://([^/]+)/.*$", r"\1", url).lower()
                if host not in ALLOWED_HOSTS:
                    warn(dw, "host %s is not GitHub; the plugin will ask the user before installing" % host)

                sha, size = d.get("sha256"), d.get("size", 0)
                if sha == "skip":
                    sha = None
                elif not sha:
                    try:
                        if local:
                            sha, size = sha256_file(local)
                        elif offline and url in prev:
                            sha, size = prev[url]
                        elif offline:
                            warn(dw, "offline: no sha256 yet")
                        else:
                            sha, size = sha256_url(url)
                    except Exception as e:
                        err(dw, "cannot download %s: %s" % (url, e))
                        continue
                entry = {"type": dtype, "url": url, "sha256": sha, "size": size}
                for k in ("arch", "python"):
                    if d.get(k):
                        entry[k] = d[k]
                if local and sha:
                    # same file through github.com (another host / CDN path); the plugin tries it when
                    # raw.githubusercontent.com fails, and still checks the same sha256
                    entry["mirrors"] = [{"type": dtype, "url": url.replace(RAW_BASE, GH_RAW_BASE), "sha256": sha}]
                downloads.extend(with_mirrors(entry))

            # ---- images are mandatory: icon + at least MIN_SCREENSHOTS screenshots ----
            icon_url = None
            if not p.get("icon"):
                err(where, "missing \"icon\" (square PNG in icons/)")
            elif p["icon"].startswith("https://"):
                icon_url = p["icon"]
            else:
                ipath, icon_url = resolve_repo_path(p["icon"])
                if not os.path.isfile(ipath):
                    err(where, "icon not found: %s" % p["icon"])
                    icon_url = None
                else:
                    check_image(where, ipath, "icon", max_kb=512)
                    icon_url += "?v=" + sha256_file(ipath)[0][:10]   # changed image -> new URL -> boxes re-download

            shots = []
            raw_shots = p.get("screenshots") or []
            if len(raw_shots) < MIN_SCREENSHOTS:
                err(where, "needs at least %d screenshot(s) in \"screenshots\" (screenshots/%s/1.png ...)" % (MIN_SCREENSHOTS, pid))
            for sh in raw_shots:
                if sh.startswith("https://"):
                    shots.append(sh)
                    continue
                spath, surl = resolve_repo_path(sh)
                if not os.path.isfile(spath):
                    err(where, "screenshot not found: %s" % sh)
                    continue
                check_image(where, spath, "screenshot", max_kb=MAX_SHOT_KB)
                shots.append(surl + "?v=" + sha256_file(spath)[0][:10])

            primary = downloads[0] if downloads else {}
            items.append({
                # fields understood by every plugin version (Item.from_dict)
                "id": pid,
                "category": p.get("category", ""),
                "group": p.get("group"),
                "name": p.get("name", pid),
                "version": str(p.get("version", "")),
                "description": p.get("description", ""),
                "updated": norm_date(p.get("updated"), where),
                "status_codes": [s for s in [p.get("subcategory")] if s] + list(p.get("tags", [])),
                "url": primary.get("url", ""),
                "host": "github" if "github" in primary.get("url", "") else "other",
                "dangerous": bool(p.get("dangerous", False)),
                "line_no": 0,
                "changelog": [[norm_date(c.get("date"), where) or "", c.get("text", "")]
                              if isinstance(c, dict) else ["", str(c)]
                              for c in p.get("changelog", [])],
                "sha256": primary.get("sha256"),
                "restart": bool(p.get("restart", False)),
                "icon_url": icon_url,
                # schema 2 extras
                "screenshots": shots,
                "downloads": downloads,
                "python": py,
                "package": p.get("package"),
                "author": p.get("author") or ((source_page(primary.get("url", "")) or "").split("/")[3:4] or [None])[0],
                "homepage": p.get("homepage") or source_page(primary.get("url", "")),
                "i18n": p.get("i18n") or {},           # {"en": {"description": "..."}, "de": {...}}
                "settings": p.get("settings") or {},
                "order": int(p.get("order", 1000)) if str(p.get("order", "")).lstrip("-").isdigit() else 1000,
                "featured": bool(p.get("featured", False)),   # {"config": ["config.plugins.X."], "files": ["/etc/enigma2/x/*.json"]}
            })

    items.sort(key=lambda it: (it["category"], it["order"], it["name"].lower()))
    items = [slim(it) for it in items]
    used = set(it["category"] for it in items)
    return {
        "schema": SCHEMA,
        "generated": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "repo": OWNER_REPO,
        "categories": [c for c in cats if c["id"] in used],
        "all_categories": cats,
        "items": items,
    }


def main():
    offline = "--offline" in sys.argv
    check = "--check" in sys.argv
    index = build(offline=offline)
    for w in warnings:
        print("WARN  " + w)
    for e in errors:
        print("ERROR " + e)
    if errors:
        print("\n%d error(s) - index.json NOT written" % len(errors))
        sys.exit(1)
    print("OK: %d item(s), %d categorie(s) in use" % (len(index["items"]), len(index["categories"])))
    if check:
        return
    out = os.path.join(ROOT, "index.json")
    old = None
    old_signed = False
    if os.path.isfile(out):
        old = load_json(out)
        old.pop("generated", None)
        old_signed = "signature" in old
        old.pop("signature", None)
    new_cmp = dict(index)
    new_cmp.pop("generated", None)
    if old == new_cmp and (old_signed or not os.environ.get("INDEX_SIGNING_KEY")):
        print("index.json unchanged")
        return
    sign_index(index)
    with io.open(out, "w", encoding="utf-8") as f:
        f.write(json.dumps(index, ensure_ascii=False, indent=1) + "\n")
    print("index.json written%s" % (" (signed)" if "signature" in index else " (NOT signed)"))


def canonical(index):
    """Exact bytes that are signed: the index without "signature", keys sorted, no spaces."""
    d = dict(index)
    d.pop("signature", None)
    return json.dumps(d, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sign_index(index):
    """Ed25519-sign the index with INDEX_SIGNING_KEY (GitHub secret, base64 32-byte seed)."""
    import base64
    key = os.environ.get("INDEX_SIGNING_KEY", "").strip()
    if not key:
        if "--require-signature" in sys.argv:
            print("ERROR INDEX_SIGNING_KEY is not set - refusing to publish an unsigned index")
            sys.exit(1)
        return
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import ed25519
    seed = base64.b64decode(key)
    index["signature"] = {
        "alg": "ed25519",
        "key": ed25519.public_key(seed).hex(),
        "sig": base64.b64encode(ed25519.sign(seed, canonical(index))).decode("ascii"),
    }


if __name__ == "__main__":
    main()
