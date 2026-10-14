#!/usr/bin/env python3
"""Novaler section: every plugin on novaler.com/dz/downloads/plugins, as published by Novaler for its
Multibox receivers, with the picture from its card.

For each card it writes packages/novaler/<id>.json, the payload under files/<id>/<version>/,
icons/<id>.png and screenshots/<id>/1.png. Payloads:
  .ipk / .deb             -> mirrored as they are
  .zip with an .ipk/.deb  -> the package inside (the "all" one, else the ARM one)
  .tar.gz / a zip of a usr/ etc/ tree -> the tarball + a small install.sh that unpacks it to /
anything else is skipped and listed.  Already imported versions are left alone, so it can run daily.

usage: python3 tools/import_novaler.py [--dry]
"""
import hashlib
import html
import io
import json
import os
import re
import sys
import tarfile
import time
import urllib.parse
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGE = "https://www.novaler.com/dz/downloads/plugins"
BASE = "https://www.novaler.com"
OWNER_REPO = "Ahmadarjan1/EnigmaPlay-Repo"
RAW = "https://raw.githubusercontent.com/%s/main/" % OWNER_REPO
UA = "Mozilla/5.0 (X11; Linux x86_64) EnigmaPlay-Store"
MAX_BYTES = 60 * 1024 * 1024
# receivers a Novaler-only package is for (the names their images report)
MODELS = ["novaler4k", "novaler4kse", "novaler4kpro", "multibox", "multiboxse", "multiboxpro"]
BOX_ONLY = re.compile(r"novacam|novaler|ultracam|camnova|novatv|wifi[-_ ]?driver|softcam", re.I)
MONTHS = {"جانفي": 1, "يناير": 1, "فيفري": 2, "فبراير": 2, "مارس": 3, "أفريل": 4, "افريل": 4, "أبريل": 4,
          "ماي": 5, "مايو": 5, "جوان": 6, "يونيو": 6, "جويلية": 7, "يوليو": 7, "أوت": 8, "اوت": 8,
          "أغسطس": 8, "سبتمبر": 9, "أكتوبر": 10, "اكتوبر": 10, "نوفمبر": 11, "ديسمبر": 12}

DRY = "--dry" in sys.argv


def notice(msg):
    print("::notice::" + msg.replace("\n", " ")[:3000])


def get(url, limit=MAX_BYTES):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=90) as r:
        data = r.read(limit + 1)
    if len(data) > limit:
        raise ValueError("too large")
    return data


def text(s):
    s = re.sub(r"<br\s*/?>|</li>|</p>", "\n", s or "", flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    lines = [" ".join(l.split()) for l in s.split("\n")]
    return "\n".join(l for l in lines if l)


def slug(s):
    s = re.sub(r"\.(zip|ipk|deb|tar\.gz|tgz|sh)$", "", s.lower())
    s = re.sub(r"^enigma2-plugin-(extensions|systemplugins|softcams|skins|picons)-", "", s)
    s = re.sub(r"[_\s-]v?\d[\w.+~-]*$", "", s) or s          # drop a trailing version / arch
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    s = re.sub(r"^novaler-(?=.)", "", s)
    return s[:40] or "plugin"


def parse_date(s):
    m = re.search(r"(\d{1,2})\s+(\S+)\s+(\d{4})", s or "")
    if m and m.group(2) in MONTHS:
        return "%s-%02d-%02d" % (m.group(3), MONTHS[m.group(2)], int(m.group(1)))
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", s or "")
    return m.group(0) if m else None


def cards(page):
    """[{name, version, date, news, file, thumb}] in page order."""
    out = []
    parts = re.split(r'(?=<img[^>]+src="[^"]*/uploads/media/software/)', page)
    for seg in parts[1:]:
        thumb = re.search(r'<img[^>]+src="([^"]+)"', seg).group(1)
        link = re.search(r'href="([^"]*/uploads/plugins/[^"]+)"', seg)
        if not link:
            continue
        name = re.search(r"<h4[^>]*>(.*?)</h4>", seg, re.S)
        alt = re.search(r'alt="([^"]*)"', seg)
        name = text(name.group(1)) if name else text(alt.group(1) if alt else "")

        def field(label):
            m = re.search(r"<strong>\s*" + label + r"\s*:?\s*</strong>\s*:?(.*?)</div>", seg, re.S)
            return text(m.group(1)) if m else ""
        news = ""
        m = re.search(r"<strong>\s*الجديد\s*:?\s*</strong>(.*?)(?:</ul>|</div>)", seg, re.S)
        if m:
            news = text(m.group(1))
        out.append({"name": name.strip(), "version": field("الإصدار") or field("الاصدار"),
                    "date": parse_date(field("تاريخ")), "news": news,
                    "file": urllib.parse.urljoin(BASE, html.unescape(link.group(1))),
                    "thumb": urllib.parse.urljoin(BASE, html.unescape(thumb))})
    return out


def arch_of(name):
    n = name.lower()
    if "aarch64" in n:
        return "aarch64"
    if "mips" in n:
        return "mipsel"
    if re.search(r"cortex|armv7|_arm|-arm|arm\b", n):
        return "arm"
    return None


def pick_package(names):
    pk = [n for n in names if n.lower().endswith((".ipk", ".deb")) and not n.startswith("__MACOSX")]
    if not pk:
        return None
    for test in (lambda n: "_all" in n.lower(), lambda n: arch_of(n) == "arm", lambda n: arch_of(n) is None):
        hit = [n for n in pk if test(n)]
        if hit:
            return sorted(hit)[-1]
    return sorted(pk)[-1]


def tree_ok(names):
    """A tarball/zip that unpacks onto / (usr/..., etc/...)."""
    roots = set()
    for n in names:
        n = n.lstrip("./")
        if not n or n.startswith("__MACOSX"):
            continue
        roots.add(n.split("/")[0])
    return bool(roots) and roots <= {"usr", "etc", "media", "var", "home", "lib"}


def to_tar(zf):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for zi in zf.infolist():
            n = zi.filename.lstrip("./")
            if not n or n.startswith("__MACOSX") or zi.is_dir():
                continue
            ti = tarfile.TarInfo(n)
            data = zf.read(zi)
            ti.size = len(data)
            ti.mode = 0o755 if n.endswith((".sh", ".py")) or "/bin/" in n else 0o644
            ti.mtime = time.time()
            tf.addfile(ti, io.BytesIO(data))
    return buf.getvalue()


def payload(fname, data):
    """-> (type, filename, bytes, note) or (None, reason)."""
    low = fname.lower()
    if low.endswith((".ipk", ".deb")):
        return (low[-3:], fname, data, "")
    if low.endswith(".sh"):
        return ("sh", fname, data, "")
    if low.endswith((".tar.gz", ".tgz")):
        try:
            with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
                names = tf.getnames()
        except Exception as e:
            return (None, "bad tar: %s" % e)
        if tree_ok(names):
            return ("tar", re.sub(r"\.tgz$", ".tar.gz", fname), data, "")
        pk = pick_package(names)
        if pk:
            with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
                return (pk.lower()[-3:], os.path.basename(pk), tf.extractfile(pk).read(), "")
        return (None, "tar without usr/ tree: %s" % ", ".join(names[:4]))
    if low.endswith(".zip"):
        try:
            zf = zipfile.ZipFile(io.BytesIO(data))
            names = zf.namelist()
        except Exception as e:
            return (None, "bad zip: %s" % e)
        pk = pick_package(names)
        if pk:
            return (pk.lower()[-3:], os.path.basename(pk), zf.read(pk), "")
        inner = [n for n in names if n.lower().endswith((".tar.gz", ".tgz")) and not n.startswith("__MACOSX")]
        if len(inner) == 1:
            return payload(os.path.basename(inner[0]), zf.read(inner[0]))
        if tree_ok(names):
            return ("tar", re.sub(r"\.zip$", ".tar.gz", fname, flags=re.I), to_tar(zf), "")
        return (None, "zip content: %s" % ", ".join(names[:5]))
    return (None, "unknown file type")


INSTALL_SH = """#!/bin/sh
# EnigmaPlay store: %(name)s %(version)s, the package Novaler publishes on novaler.com.
# Downloads the archive from the store repository, checks it and unpacks it onto /.
URL="%(url)s"
SHA="%(sha)s"
TMP="/tmp/enigmaplay-%(id)s.tar.gz"
rm -f "$TMP"
echo "Downloading %(name)s ..."
wget -q -O "$TMP" "$URL" 2>/dev/null || curl -fsSL -o "$TMP" "$URL" || { echo "Download failed"; rm -f "$TMP"; exit 1; }
if command -v sha256sum >/dev/null 2>&1; then
  echo "$SHA  $TMP" | sha256sum -c - >/dev/null 2>&1 || { echo "Checksum mismatch"; rm -f "$TMP"; exit 1; }
fi
tar -xzf "$TMP" -C / || { echo "Unpacking failed"; rm -f "$TMP"; exit 1; }
rm -f "$TMP"
sync
echo "%(name)s %(version)s installed"
exit 0
"""


def images(pid, thumb_bytes):
    from PIL import Image
    im = Image.open(io.BytesIO(thumb_bytes)).convert("RGBA")
    # screenshot: the card picture as Novaler shows it
    shot = im.convert("RGB")
    if shot.width > 1280:
        shot = shot.resize((1280, round(shot.height * 1280 / shot.width)), Image.LANCZOS)
    sdir = os.path.join(ROOT, "screenshots", pid)
    os.makedirs(sdir, exist_ok=True)
    shot.save(os.path.join(sdir, "1.png"), optimize=True)
    # icon: the picture fitted into a 256 square
    side = 256
    ic = Image.new("RGBA", (side, side), (255, 255, 255, 255))
    fit = im.copy()
    fit.thumbnail((side - 16, side - 16), Image.LANCZOS)
    ic.paste(fit, ((side - fit.width) // 2, (side - fit.height) // 2), fit)
    ic.save(os.path.join(ROOT, "icons", pid + ".png"), optimize=True)


def python_of(name):
    n = name.lower()
    if re.search(r"py(thon)?-?3", n):
        return ["3"]
    if re.search(r"py(thon)?-?2", n):
        return ["2"]
    return ["2", "3"]


def main():
    page = get(PAGE).decode("utf-8", "replace")
    found = cards(page)
    if len(found) < 5:
        print("::error::only %d cards on %s; page layout changed?" % (len(found), PAGE))
        return 1
    pkg_dir = os.path.join(ROOT, "packages", "novaler")
    os.makedirs(pkg_dir, exist_ok=True)
    added, kept, skipped, ids = [], [], [], set()
    for c in found:
        fname = urllib.parse.unquote(c["file"].rsplit("/", 1)[-1])
        pid = "novaler-" + slug(fname if len(slug(c["name"])) < 3 else c["name"])
        base, n = pid, 2
        while pid in ids:
            pid, n = "%s-%d" % (base, n), n + 1
        ids.add(pid)
        version = re.sub(r"[^\w.+~-]", "", (c["version"] or "").replace(" ", "")) or \
            (re.search(r"[_-]v?(\d[\d.]*)", fname) or [None, "1.0"])[1]
        mpath = os.path.join(pkg_dir, pid + ".json")
        old = json.load(open(mpath, encoding="utf-8")) if os.path.exists(mpath) else None
        if old and old.get("version") == version and old.get("novaler_file") == c["file"]:
            kept.append(pid)
            continue
        if DRY:
            notice("would add %s: %s %s (%s)" % (pid, c["name"], version, fname))
            continue
        try:
            data = get(c["file"])
        except Exception as e:
            skipped.append("%s (%s): %s" % (c["name"], fname, e))
            continue
        res = payload(fname, data)
        if res[0] is None:
            skipped.append("%s (%s): %s" % (c["name"], fname, res[1]))
            continue
        kind, out_name, blob, _ = res
        out_name = re.sub(r"[^\w.+~-]", "_", out_name)
        rel_dir = "files/%s/%s" % (pid, version)
        os.makedirs(os.path.join(ROOT, rel_dir), exist_ok=True)
        with open(os.path.join(ROOT, rel_dir, out_name), "wb") as f:
            f.write(blob)
        dl = {"type": kind if kind != "tar" else "sh", "file": "%s/%s" % (rel_dir, out_name)}
        if kind == "tar":
            sh_rel = "%s/install.sh" % rel_dir
            with open(os.path.join(ROOT, sh_rel), "w", encoding="utf-8", newline="\n") as f:
                f.write(INSTALL_SH % {"name": c["name"].replace('"', ""), "version": version, "id": pid,
                                      "url": RAW + dl["file"], "sha": hashlib.sha256(blob).hexdigest()})
            dl = {"type": "sh", "file": sh_rel}
        else:
            a = arch_of(out_name)
            if a:
                dl["arch"] = a
        try:
            images(pid, get(c["thumb"], 8 * 1024 * 1024))
        except Exception as e:
            skipped.append("%s: picture: %s" % (c["name"], e))
            continue
        news = c["news"]
        desc = "النسخة التي تنشرها شركة نوفالر لأجهزتها Multibox على موقعها novaler.com."
        if news:
            desc += "\nالجديد:\n" + news
        today = time.strftime("%Y-%m-%d", time.gmtime())
        man = {
            "id": pid,
            "name": c["name"],
            "category": "novaler",
            "version": version,
            "updated": c["date"] or today,
            "description": desc,
            "i18n": {"en": {"description": "The build Novaler publishes for its Multibox receivers on novaler.com." +
                            ("\nWhat's new:\n" + news if news else "")}},
            "python": python_of(fname + " " + c["name"]),
            "restart": True,
            "icon": "icons/%s.png" % pid,
            "screenshots": ["screenshots/%s/1.png" % pid],
            "downloads": [dl],
            "author": "Novaler",
            "homepage": PAGE,
            "batch": "novaler",
            "novaler_file": c["file"],
            "changelog": ([{"date": today, "text": "المصدر: موقع نوفالر (novaler.com) — الإصدار %s" % version}] +
                          (old or {}).get("changelog", []))[:20],
            "updated_at": int(time.time()),
        }
        if BOX_ONLY.search(c["name"] + " " + fname):
            man["models"] = MODELS
        with open(mpath, "w", encoding="utf-8") as f:
            json.dump(man, f, ensure_ascii=False, indent=2)
            f.write("\n")
        added.append("%s %s [%s]" % (pid, version, dl["type"]))
    notice("Novaler: %d cards, %d added/updated, %d unchanged, %d skipped" % (len(found), len(added), len(kept), len(skipped)))
    for i in range(0, len(added), 15):
        notice("added: " + " | ".join(added[i:i + 15]))
    for i in range(0, len(skipped), 8):
        notice("skipped: " + " | ".join(skipped[i:i + 8]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
