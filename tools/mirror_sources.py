#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Backup of third-party download sources + fallback links (run by .github/workflows/mirror-sources.yml).

1. Mirror: the upstream repositories in MIRROR_REPOS are cloned and every file is uploaded as an
   asset of the releases "mirror-0" ... "mirror-f" of this repository (files are only added or
   refreshed, never removed, so a deleted upstream file stays available). The API route
   /m/<key> redirects to the asset, so links keep their folder layout. Text files get their
   upstream links rewritten to /m/..., so a mirrored installer downloads its payload from the
   mirror as well. Progress (sha256 of every uploaded file) is kept in mirror/state.json.
2. Alternatives: the LinuxsatPanel catalog (addons xml + its built-in script lists) is parsed and
   matched by plugin / package name to the store items.
3. Writes mirror/map.json on main:
     {"items": {"<download url>": {"alive": bool, "mirror": "<url>|null", "alt": [{type,url,name}]}}}
   tools/build_index.py adds these as "mirrors" to every download (the plugin tries them in order
   when the primary link fails) and swaps a dead primary for its mirror.
4. --revive: hidden manifests (packages/*/_<id>.json, hidden because their link died) that now have
   a mirror or an alternative are published again.

Usage: python3 tools/mirror_sources.py [--work /tmp/up] [--revive] [--no-clone]
"""
import argparse
import concurrent.futures as cf
import datetime
import glob
import io
import json
import os
import re
import shutil
import subprocess
import sys
import hashlib
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
STORE_REPO = os.environ.get("GITHUB_REPOSITORY", "Ahmadarjan1/EnigmaPlay-Repo")
WORKER = os.environ.get("MIRROR_WORKER", "https://enigmaplay-api.ahmadalarjan2.workers.dev")
MAX_FILE = 1900 * 1024 * 1024        # release asset limit is 2 GB
MAX_UPLOADS = int(os.environ.get("MIRROR_MAX_UPLOADS", "800"))   # GITHUB_TOKEN: 1000 API requests / hour
TEXT_EXT = (".sh", ".txt", ".cfg", ".conf", ".json", ".xml", ".py", ".list", "")
UA = {"User-Agent": "Wget/1.21.3"}
STATE = os.path.join(ROOT, "mirror", "state.json")

# Repositories copied completely into the mirror (host, owner, repo)
MIRROR_REPOS = [
    # LinuxsatPanel packages (free, published for distribution): backup copy, credited on every plugin page.
    ("github.com", "Belfagor2005", "upload"),
]
EXTRA_REPOS = [r.split("/") for r in os.environ.get("MIRROR_EXTRA", "").split() if r.count("/") == 2]

LINUXSAT_XML = os.environ.get("LINUXSAT_XML", "https://raw.githubusercontent.com/Belfagor2005/upload/main/fill/addons_2024.xml")
LINUXSAT_EXTRA = os.path.join(ROOT, "mirror", "linuxsat_builtin.json")


def log(*a):
    print(*a)
    sys.stdout.flush()


def http_get(url, n=None, timeout=40):
    h = dict(UA)
    if n:
        h["Range"] = "bytes=0-%d" % (n - 1)
    with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=timeout) as r:
        return r.read(n or 64 * 1024 * 1024)


def api_json(path):
    h = {"User-Agent": "EnigmaPlay-mirror", "Accept": "application/vnd.github+json"}
    if os.environ.get("GITHUB_TOKEN"):
        h["Authorization"] = "Bearer " + os.environ["GITHUB_TOKEN"]
    with urllib.request.urlopen(urllib.request.Request("https://api.github.com" + path, headers=h), timeout=40) as r:
        return json.loads(r.read().decode("utf-8"))


def looks_valid(data, kind):
    head = (data or b"")[:512]
    if not head:
        return False
    low = head.lstrip()[:256].lower()
    if low.startswith(b"<!doctype") or low.startswith(b"<html") or b"<html" in low[:120]:
        return False
    if kind in ("ipk", "deb"):
        return head.startswith(b"!<arch>") or head[:2] == b"\x1f\x8b"
    return True


def alive(url, kind):
    for _ in range(2):
        try:
            return looks_valid(http_get(url, n=1024), kind)
        except urllib.error.HTTPError as e:
            if e.code in (404, 410, 401, 403):
                return False
        except Exception:
            pass
    return None          # unknown (network trouble): keep the previous state


# ------------------------------------------------------------------ storage: GitHub release assets
# A mirrored file "gh/<owner>/<repo>/<path>" is stored as the asset sha1(key) in the
# release "mirror-<first hex digit>" (16 releases, < 1000 assets each). The worker route
# /m/<key> redirects to it, so links keep their directory layout ($git_url/version keeps working).
def asset_of(key):
    h = hashlib.sha1(key.encode("utf-8")).hexdigest()
    return "mirror-" + h[0], h


def release_url(key):
    tag, name = asset_of(key)
    return "https://github.com/%s/releases/download/%s/%s" % (STORE_REPO, tag, name)


def worker_url(key):
    return WORKER + "/m/" + urllib.parse.quote(key)


class Releases(object):
    def __init__(self):
        self.token = os.environ.get("GITHUB_TOKEN")
        self.rel = {}            # tag -> {"id", "assets": {name: id}}
        self.calls = 0
        self.uploads = 0

    def api(self, method, url, data=None, ctype="application/json"):
        self.calls += 1
        h = {"Authorization": "Bearer " + self.token, "Accept": "application/vnd.github+json",
             "User-Agent": "EnigmaPlay-mirror"}
        if data is not None:
            h["Content-Type"] = ctype
        req = urllib.request.Request(url, data=data, headers=h, method=method)
        with urllib.request.urlopen(req, timeout=600) as r:
            body = r.read()
        return json.loads(body.decode("utf-8")) if body else {}

    def ensure(self, tag):
        if tag in self.rel:
            return self.rel[tag]
        base = "https://api.github.com/repos/%s/releases" % STORE_REPO
        try:
            r = self.api("GET", base + "/tags/" + tag)
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise
            r = self.api("POST", base, json.dumps({
                "tag_name": tag, "name": "Mirror " + tag[-1], "prerelease": True, "make_latest": "false",
                "body": "Automatic backup of third-party download sources (do not edit)."}).encode())
        assets, page = {}, 1
        while True:
            lst = self.api("GET", base + "/%d/assets?per_page=100&page=%d" % (r["id"], page))
            for a in lst:
                assets[a["name"]] = a["id"]
            if len(lst) < 100:
                break
            page += 1
        self.rel[tag] = {"id": r["id"], "assets": assets}
        return self.rel[tag]

    def delete(self, key):
        tag, name = asset_of(key)
        r = self.ensure(tag)
        aid = r["assets"].pop(name, None)
        if aid:
            self.api("DELETE", "https://api.github.com/repos/%s/releases/assets/%d" % (STORE_REPO, aid))

    def put(self, key, data):
        tag, name = asset_of(key)
        r = self.ensure(tag)
        if name in r["assets"]:
            self.api("DELETE", "https://api.github.com/repos/%s/releases/assets/%d" % (STORE_REPO, r["assets"][name]))
        a = self.api("POST", "https://uploads.github.com/repos/%s/releases/%d/assets?name=%s" % (STORE_REPO, r["id"], name),
                     data, "application/octet-stream")
        r["assets"][name] = a["id"]
        self.uploads += 1


# ------------------------------------------------------------------ mirror
def mkey(host, owner, repo):
    return "%s/%s/%s" % ("gl" if host == "gitlab.com" else "gh", owner, repo)


def rewrite_rules(repos):
    """[(regex, replacement)] mapping upstream raw links of mirrored repos to the worker mirror route."""
    rules = []
    for host, owner, repo, branch in repos:
        o, r, b = re.escape(owner), re.escape(repo), re.escape(branch)
        dst = worker_url(mkey(host, owner, repo)) + "/"
        if host == "gitlab.com":
            rules.append((re.compile(r"https?://gitlab\.com/%s/%s/(?:-/)?raw/%s/" % (o, r, b), re.I), dst))
        else:
            rules.append((re.compile(r"https?://raw\.githubusercontent\.com/%s/%s/(?:refs/heads/)?%s/" % (o, r, b), re.I), dst))
            rules.append((re.compile(r"https?://github\.com/%s/%s/(?:raw|blob)/(?:refs/heads/)?%s/" % (o, r, b), re.I), dst))
            rules.append((re.compile(r"https?://github\.com/%s/%s/archive/(?:refs/heads/)?%s\.tar\.gz" % (o, r, b), re.I),
                          worker_url(mkey(host, owner, repo) + "/__archive__/%s.tar.gz" % branch)))
    return rules


def key_for(url, repos):
    """Mirror key of an upstream URL (None when it is not inside a mirrored repo)."""
    u = url.split("?")[0].split("#")[0]
    for host, owner, repo, branch in repos:
        o, r, b = re.escape(owner), re.escape(repo), re.escape(branch)
        if host == "gitlab.com":
            pats = [r"https?://gitlab\.com/%s/%s/(?:-/)?raw/%s/(.+)$" % (o, r, b)]
        else:
            pats = [r"https?://raw\.githubusercontent\.com/%s/%s/(?:refs/heads/)?%s/(.+)$" % (o, r, b),
                    r"https?://github\.com/%s/%s/(?:raw|blob)/(?:refs/heads/)?%s/(.+)$" % (o, r, b)]
        for pat in pats:
            m = re.match(pat, u, re.I)
            if m:
                return mkey(host, owner, repo) + "/" + urllib.parse.unquote(m.group(1))
    return None


def rewrite_text(data, rules):
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return data
    new = text
    for rx, dst in rules:
        new = rx.sub(dst, new)
    return new.encode("utf-8") if new != text else data


def is_text(path, data):
    ext = os.path.splitext(path)[1].lower()
    return ext in TEXT_EXT and len(data) < 2 * 1024 * 1024 and b"\x00" not in data[:8192]


def clone(host, owner, repo, work):
    dst = os.path.join(work, "%s__%s__%s" % (host, owner, repo))
    if os.path.isdir(dst):
        shutil.rmtree(dst)
    url = "https://%s/%s/%s.git" % (host, owner, repo)
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    try:
        r = subprocess.run(["git", "clone", "-q", "--depth", "1", url, dst], env=env,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=3600)
    except subprocess.TimeoutExpired:
        return None, None
    if r.returncode != 0:
        log("  clone failed %s: %s" % (url, r.stderr.decode("utf-8", "replace").strip()[:200]))
        return None, None
    branch = subprocess.run(["git", "-C", dst, "rev-parse", "--abbrev-ref", "HEAD"],
                            stdout=subprocess.PIPE).stdout.decode().strip() or "main"
    return dst, branch


def default_branch(host, owner, repo):
    url = "https://%s/%s/%s.git" % (host, owner, repo)
    try:
        r = subprocess.run(["git", "ls-remote", "--symref", url, "HEAD"], stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, timeout=120, env=dict(os.environ, GIT_TERMINAL_PROMPT="0"))
    except subprocess.TimeoutExpired:
        return None
    m = re.search(r"ref: refs/heads/(\S+)\s+HEAD", r.stdout.decode("utf-8", "replace"))
    return m.group(1) if r.returncode == 0 and m else None


BLOCKED_NAME = re.compile(r"eliesat", re.I)    # never copy files of this source, wherever they are found


def load_state():
    if os.path.isfile(STATE):
        with io.open(STATE, encoding="utf-8") as f:
            return json.load(f)
    return {"repos": {}, "files": {}}


def save_state(state):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    with io.open(STATE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=0, sort_keys=True)


def mirror_repos(state, work, no_clone):
    """Clone every mirrored repo and upload new / changed files. Files are never deleted from the mirror."""
    rel = Releases()
    known = []
    for host, owner, repo in MIRROR_REPOS + [tuple(x) for x in EXTRA_REPOS]:
        st = state["repos"].get(mkey(host, owner, repo), {})
        known.append((host, owner, repo, st.get("branch") or "main"))
    if no_clone or not rel.token:
        if not rel.token:
            log("GITHUB_TOKEN missing: not uploading")
        return known
    # default branches first (the rewrite rules need all of them); then clone one repo at a time
    repos, reachable = [], set()
    for host, owner, repo, br in known:
        k = mkey(host, owner, repo)
        st = state["repos"].setdefault(k, {})
        branch = default_branch(host, owner, repo)
        if not branch:
            st["upstream"] = "unreachable"
            st.setdefault("unreachable_since", datetime.date.today().isoformat())
            repos.append((host, owner, repo, br))
            log("  %-40s upstream unreachable - keeping the mirrored copy" % k)
            continue
        st.pop("unreachable_since", None)
        st.update({"branch": branch, "upstream": "ok", "checked": datetime.date.today().isoformat()})
        repos.append((host, owner, repo, branch))
        reachable.add(k)
    rules = rewrite_rules(repos)
    files = state["files"]
    pending = 0
    # purge files of repositories that are no longer mirrored
    keep = set(mkey(h, o, r) for h, o, r, _b in known)
    stale = [k for k in list(files) if "/".join(k.split("/")[:3]) not in keep]
    for k in stale:
        if rel.calls >= MAX_UPLOADS + 150:
            pending += 1
            continue
        try:
            rel.delete(k)
        except Exception as e:
            log("  delete failed %s: %s" % (k, e))
            pending += 1
            continue
        files.pop(k, None)
    for rk in list(state["repos"]):
        if rk not in keep and not any(f.startswith(rk + "/") for f in files):
            state["repos"].pop(rk, None)
    if stale:
        log("purged %d mirrored file(s) of removed sources, %d left" % (len(stale) - pending, pending))
        save_state(state)
    for host, owner, repo, branch in repos:
        k = mkey(host, owner, repo)
        if k not in reachable:
            continue
        if rel.uploads >= MAX_UPLOADS:
            pending += 1          # unknown amount; the next run continues
            continue
        src, _ = clone(host, owner, repo, work)
        if not src:
            continue
        todo = []
        for dp, dns, fns in os.walk(src):
            dns[:] = [d for d in dns if d != ".git"]
            for fn in fns:
                sp = os.path.join(dp, fn)
                if os.path.islink(sp) or os.path.getsize(sp) > MAX_FILE or BLOCKED_NAME.search(sp):
                    continue
                todo.append((k + "/" + os.path.relpath(sp, src).replace(os.sep, "/"), sp))
        if host == "github.com":
            arc = os.path.join(work, "%s.archive.tar.gz" % k.replace("/", "_"))
            subprocess.run(["git", "-C", src, "archive", "--format=tar.gz", "--prefix=%s-%s/" % (repo, branch),
                            "-o", arc, "HEAD"], check=False)
            if os.path.isfile(arc):
                todo.append((k + "/__archive__/%s.tar.gz" % branch, arc))
        n_up = 0
        for key, sp in todo:
            with open(sp, "rb") as f:
                data = f.read()
            if is_text(sp, data):
                data = rewrite_text(data, rules)
            sha = hashlib.sha256(data).hexdigest()
            if files.get(key, {}).get("sha256") == sha:
                continue
            if rel.uploads >= MAX_UPLOADS or rel.calls >= MAX_UPLOADS + 150:
                pending += 1
                continue
            try:
                rel.put(key, data)
            except Exception as e:
                log("  upload failed %s: %s" % (key, e))
                pending += 1
                continue
            files[key] = {"sha256": sha, "size": len(data), "date": datetime.date.today().isoformat()}
            n_up += 1
        state["repos"][k]["files"] = sum(1 for x in files if x.startswith(k + "/"))
        shutil.rmtree(src, ignore_errors=True)
        for _, sp in todo:
            if sp.endswith(".archive.tar.gz") and os.path.isfile(sp):
                os.remove(sp)
        log("  %-40s %5d files, %4d uploaded now (branch %s)" % (k, len(todo), n_up, branch))
        save_state(state)
    state["pending_uploads"] = pending
    state["last_run"] = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M")
    log("mirror: %d uploads, %d API calls, %d files still pending (next run)" % (rel.uploads, rel.calls, pending))
    return repos


# ------------------------------------------------------------------ LinuxsatPanel alternatives
STOP = {"all", "py3", "py2", "oe2", "oe20", "oe25", "r0", "by", "v", "new", "mod", "plugin", "enigma2", "extensions",
        "systemplugins", "lululla", "iet", "e2", "for", "the"}
ARCH_RE = re.compile(r"(aarch64|armhf|arm64|cortexa|mipsel|mips32|mips|_arm[_.-]|-arm\.|x86|armv7)", re.I)


def norm(s):
    s = (s or "").lower()
    s = re.sub(r"\.(ipk|deb|tar\.gz|zip|sh)$", "", s)
    s = re.sub(r"enigma2-plugin-(extensions|systemplugins|skins?|softcams?)-", "", s)
    s = re.sub(r"[_ ]v?\.?\d[\w.+~-]*", "", s)
    toks = [t for t in re.split(r"[^a-z0-9]+", s) if t and t not in STOP and not t.isdigit()]
    return "".join(toks)


def linuxsat_catalog():
    items = []
    try:
        xml = http_get(LINUXSAT_XML).decode("utf-8", "replace")
        for cont, body in re.findall(r'<plugins cont="(.*?)">(.*?)</plugins>', xml, re.S):
            for name, url in re.findall(r'<plugin name="(.*?)".*?<url>"(.*?)"</url>', body, re.S):
                url = url.strip()
                kind = "deb" if url.endswith(".deb") else "ipk" if url.endswith(".ipk") else None
                if kind and url.startswith("https://"):
                    items.append({"section": cont.strip(), "name": name.strip(), "type": kind, "url": url})
        log("linuxsat xml: %d entries" % len(items))
    except Exception as e:
        log("linuxsat xml unavailable (%s); using the saved copy" % e)
        return None
    if os.path.isfile(LINUXSAT_EXTRA):
        with io.open(LINUXSAT_EXTRA, encoding="utf-8") as f:
            items += json.load(f)
    return items


def build_alt_index(cat):
    idx = {}
    for e in cat:
        if e["type"] in ("ipk", "deb") and ARCH_RE.search(e["url"].rsplit("/", 1)[-1]):
            continue      # arch specific packages are not safe as a generic fallback
        keys = {norm(e["name"])}
        if e["type"] in ("ipk", "deb"):
            keys.add(norm(e["url"].rsplit("/", 1)[-1].split("_")[0]))
        for k in keys:
            if len(k) >= 4:
                idx.setdefault(k, []).append(e)
    return idx


NO_ALT_CATEGORIES = ("images", "feeds")     # an image / feed is never replaceable by a "similar" package
AMBIGUOUS = set()


def item_keys(m, url):
    keys = {norm(m.get("name")), norm(m.get("id")), norm(re.sub(r"-\d+$", "", m.get("id", "")))}
    parts = url.rstrip("/").split("/")
    if len(parts) > 2:
        keys.add(norm(parts[-2]))
    return {k for k in keys if len(k) >= 4}


def find_ambiguous(all_items):
    """Keys shared by store items with different names (e.g. "Openatv-6.0" / "Openatv-7.1" -> "openatv")."""
    names = {}
    for m, url in all_items:
        base = re.sub(r"-\d+$", "", (m.get("id") or "").lower())
        for k in item_keys(m, url):
            names.setdefault(k, set()).add(base)
    AMBIGUOUS.clear()
    AMBIGUOUS.update(k for k, v in names.items() if len(v) > 1)


def alternatives(m, url, idx):
    if m.get("category") in NO_ALT_CATEGORIES:
        return []
    keys = item_keys(m, url)
    seen, out = set(), []
    for k in keys:
        if k in AMBIGUOUS:
            continue
        for e in idx.get(k, []):
            if e["url"] in seen or e["url"] == url:
                continue
            seen.add(e["url"])
            out.append({"type": e["type"], "url": e["url"], "name": e["name"]})
    # one ipk + one deb is enough (box picks the one for its package manager), plus scripts
    best, have = [], set()
    for e in out:
        if e["type"] in have and e["type"] != "sh":
            continue
        have.add(e["type"])
        best.append(e)
    return best[:3]


# ------------------------------------------------------------------ main
def manifests():
    for p in sorted(glob.glob(os.path.join(ROOT, "packages", "*", "*.json"))):
        try:
            with io.open(p, encoding="utf-8") as f:
                m = json.load(f)
        except Exception:
            continue
        if isinstance(m, dict):
            yield p, m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", default="/tmp/mirror-upstream")
    ap.add_argument("--no-clone", action="store_true", help="only refresh map.json (no clone / upload)")
    ap.add_argument("--revive", action="store_true")
    a = ap.parse_args()
    os.makedirs(a.work, exist_ok=True)

    state = load_state()
    repos = mirror_repos(state, a.work, a.no_clone)
    save_state(state)
    files = state["files"]

    map_path = os.path.join(ROOT, "mirror", "map.json")
    old = {}
    if os.path.isfile(map_path):
        with io.open(map_path, encoding="utf-8") as f:
            old = json.load(f).get("items", {})

    cat = linuxsat_catalog()
    cat_path = os.path.join(ROOT, "mirror", "linuxsat.json")
    if cat is None and os.path.isfile(cat_path):
        with io.open(cat_path, encoding="utf-8") as f:
            cat = json.load(f)
    cat = [e for e in (cat or []) if not BLOCKED_NAME.search(e.get("name", "") + e.get("url", ""))]
    idx = build_alt_index(cat)

    jobs = []
    for p, m in manifests():
        for d in m.get("downloads", []):
            if d.get("url"):
                jobs.append((p, m, d["url"], d.get("type", "sh")))

    find_ambiguous([(m, url) for p, m, url, kind in jobs])

    def probe(j):
        return j[2], alive(j[2], j[3])

    # scripts that pull anything from a blocked source are taken out of the store at once
    BLOCKED = re.compile(rb"eliesat", re.I)

    def blocked(u):
        try:
            return bool(BLOCKED.search(http_get(u, n=300000)))
        except Exception:
            return False
    sh_urls = sorted({j[2] for j in jobs if j[3] == "sh"})
    with cf.ThreadPoolExecutor(16) as ex:
        bad = {u for u, b in zip(sh_urls, ex.map(blocked, sh_urls)) if b}
    if bad:
        log("blocked scripts: %d %s" % (len(bad), sorted(bad)[:5]))

    with cf.ThreadPoolExecutor(16) as ex:
        live = dict(ex.map(probe, jobs))

    alt_urls = sorted({e["url"] for p, m, url, kind in jobs for e in alternatives(m, url, idx)})
    with cf.ThreadPoolExecutor(16) as ex:
        alt_live = dict(zip(alt_urls, ex.map(lambda u: alive(u, "ipk" if u.endswith((".ipk", ".deb")) else "sh"), alt_urls)))

    def mirror_of(url):
        k = key_for(url, repos)
        return release_url(k) if k and k in files else None

    items, revived, hidden = {}, [], []
    for p, m, url, kind in jobs:
        prev = old.get(url, {})
        ok = live.get(url)
        if ok is None:
            ok = prev.get("alive", True)
        alts = [e for e in alternatives(m, url, idx) if alt_live.get(e["url"]) is not False]
        for e in list(alts):
            mu = mirror_of(e["url"])
            if mu:
                alts.append({"type": e["type"], "url": mu, "name": e["name"] + " (mirror)"})
        entry = {"alive": bool(ok), "mirror": mirror_of(url), "alt": alts[:5]}
        if url in bad:
            entry["blocked"] = True
        if not ok:
            entry["dead_since"] = prev.get("dead_since") or datetime.date.today().isoformat()
        items[url] = entry

    if a.revive:
        for p, m in manifests():
            name = os.path.basename(p)
            if not name.startswith("_") or m.get("batch") not in ("bulk1", "linuxsat", "dev-source"):
                continue
            e = items.get(((m.get("downloads") or [{}])[0]).get("url"))
            if not e or e["alive"] or not (e["mirror"] or e["alt"]):
                continue
            target = os.path.join(os.path.dirname(p), name[1:])
            if os.path.exists(target):
                continue
            with io.open(target, "w", encoding="utf-8") as f:
                f.write(json.dumps(m, ensure_ascii=False, indent=2) + "\n")
            os.remove(p)
            revived.append(m.get("id"))

        # the other way round: an imported item whose link is dead for 2+ days and has no backup is hidden
        limit = (datetime.date.today() - datetime.timedelta(days=2)).isoformat()
        for p, m in manifests():
            name = os.path.basename(p)
            if name.startswith("_") or m.get("id") == "enigmaplay" or not (m.get("downloads") or [{}])[0].get("url"):
                continue
            e = items.get(((m.get("downloads") or [{}])[0]).get("url"))
            if e and e.get("blocked"):
                os.rename(p, os.path.join(os.path.dirname(p), "_" + name))
                hidden.append(m.get("id"))
                continue
            if e and not e["alive"] and not e["mirror"] and not e["alt"] and e.get("dead_since", "9") <= limit:
                os.rename(p, os.path.join(os.path.dirname(p), "_" + name))
                hidden.append(m.get("id"))

    out = {"generated": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"), "items": items}
    with io.open(map_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=0, sort_keys=True)
    with io.open(cat_path, "w", encoding="utf-8") as f:
        json.dump(cat, f, ensure_ascii=False, indent=0)

    dead = [u for u, e in items.items() if not e["alive"]]
    covered = [u for u in dead if items[u]["mirror"] or items[u]["alt"]]
    log("links: %d, dead: %d (covered: %d), with mirror: %d, with alternative: %d, mirrored files: %d"
        % (len(items), len(dead), len(covered), sum(1 for e in items.values() if e["mirror"]),
           sum(1 for e in items.values() if e["alt"]), len(files)))
    if hidden:
        log("hidden %d dead item(s) without backup: %s" % (len(hidden), ", ".join(hidden)))
    if revived:
        log("revived %d hidden item(s): %s" % (len(revived), ", ".join(revived)))
    gh_out = os.environ.get("GITHUB_OUTPUT")
    if gh_out:
        with open(gh_out, "a") as f:
            f.write("pending=%d\nrevived=%d\n" % (state.get("pending_uploads", 0), len(revived)))


if __name__ == "__main__":
    main()
