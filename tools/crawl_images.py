#!/usr/bin/env python3
"""Image sites without a JSON feed, turned into the same JSON the official servers give
({category: {file: {"name", "link"}}}), one file per receiver model:

    images/pure2/<model>.json     PurE2 (pur-e2.club/OU/images, directory listing per version/brand)
    images/novaler/<model>.json   Novaler (novaler.com downloads: images and backups per box)

The links still point at the original site; the store only reads these lists.
Run by .github/workflows/images-crawl.yml (daily); safe to run by hand.
"""
import json
import os
import re
import sys
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "images")
UA = {"User-Agent": "Mozilla/5.0 (EnigmaPlay image index)"}


def get(url, timeout=40):
    r = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout)
    return r.read().decode("utf-8", "replace")


def head_ok(url):
    try:
        req = urllib.request.Request(url, headers=UA, method="HEAD")
        r = urllib.request.urlopen(req, timeout=30)
        return r.status == 200 and "html" not in (r.headers.get("Content-Type") or "")
    except Exception:
        return False


def write(source, per_model):
    if not per_model:                              # site down: keep the lists we have
        raise RuntimeError("%s: nothing found, lists left unchanged" % source)
    d = os.path.join(OUT, source)
    os.makedirs(d, exist_ok=True)
    keep = set()
    for model, cats in per_model.items():
        if not re.match(r"^[a-z0-9_+-]{2,40}$", model):
            continue
        keep.add(model + ".json")
        body = json.dumps(cats, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
        p = os.path.join(d, model + ".json")
        old = open(p, encoding="utf-8").read() if os.path.exists(p) else None
        if old != body:
            with open(p, "w", encoding="utf-8") as f:
                f.write(body)
    for n in os.listdir(d):                       # models the site dropped
        if n.endswith(".json") and n not in keep:
            os.remove(os.path.join(d, n))
    print("%s: %d models" % (source, len(keep)))


# ---------------------------------------------------------------- PurE2
PURE = "https://pur-e2.club/OU/images/"


def crawl_pure2():
    root = get(PURE + "index.php?dir=")
    versions = sorted(set(re.findall(r'index\.php\?dir=(\d+(?:\.\d+)*)/"', root)), reverse=True)
    per_model = {}
    direct_checked = None
    for ver in versions:
        page = get(PURE + "index.php?dir=%s/" % ver)
        brands = sorted(set(re.findall(r'index\.php\?dir=%s/([A-Za-z0-9_.-]+)/"' % re.escape(ver), page)))
        for brand in brands:
            try:
                bp = get(PURE + "index.php?dir=%s/%s/" % (ver, brand))
            except Exception as e:
                print("pure2 %s/%s: %r" % (ver, brand, e))
                continue
            files = sorted(set(re.findall(r'&(?:amp;)?file=([A-Za-z0-9_.+-]+\.zip)"', bp)))
            for fn in files:
                m = re.match(r"^([a-z0-9_+]+)-PurE2-", fn, re.I)
                if not m or "recovery" in fn.lower():
                    continue
                model = m.group(1).lower()
                link = PURE + "%s/%s/%s" % (ver, brand, urllib.parse.quote(fn))
                if direct_checked is None:            # the plain file path must really serve the zip
                    direct_checked = head_ok(link)
                    print("pure2 direct links: %s" % direct_checked)
                if not direct_checked:
                    link = PURE + "index.php?dir=%s/%s/&file=%s" % (ver, brand, urllib.parse.quote(fn))
                cat = "PurE2 %s" % ver
                per_model.setdefault(model, {}).setdefault(cat, {})[fn] = {"name": fn, "link": link}
    write("pure2", per_model)


# ---------------------------------------------------------------- Novaler
NOVALER = "https://www.novaler.com"


def crawl_novaler():
    pages = set()
    for section in ("/downloads/enigma2", "/downloads/enigma2-backups"):
        try:
            html = get(NOVALER + section)
        except Exception as e:
            print("novaler %s: %r" % (section, e))
            continue
        pages.update(re.findall(r'href="(/downloads/enigma2(?:-backups2)?/[a-z0-9-]+)"', html))
    per_model = {}
    for pg in sorted(pages):
        try:
            html = get(NOVALER + pg)
        except Exception as e:
            print("novaler %s: %r" % (pg, e))
            continue
        for path in sorted(set(re.findall(r'href="(/uploads/[^"]+\.zip)"', html))):
            fn = path.rsplit("/", 1)[-1]
            low = fn.lower()
            if "recovery" in low:
                continue
            m = re.search(r"(novaler4k(?:se|pro)?|multibox(?:se|pro)?)", low)
            if not m:
                continue
            model = m.group(1)
            distro = path.split("/")[-2]
            backup = "backup" in low
            cat = "Novaler %s%s" % (distro, " backup" if backup else "")
            per_model.setdefault(model, {}).setdefault(cat, {})[fn] = {
                "name": fn, "link": NOVALER + urllib.parse.quote(path)}
    # the boxes are known as novaler4k* by openATV/EGAMI and as multibox* by OpenPLi/Open Vision
    alias = {"multibox": "novaler4k", "multiboxse": "novaler4kse", "multiboxpro": "novaler4kpro"}
    merged = {}
    for model, cats in per_model.items():
        for name in {model, alias.get(model, model)} | {k for k, v in alias.items() if v == model}:
            for cat, files in cats.items():
                merged.setdefault(name, {}).setdefault(cat, {}).update(files)
    write("novaler", merged)


if __name__ == "__main__":
    which = sys.argv[1:] or ["pure2", "novaler"]
    ok = True
    for w in which:
        try:
            {"pure2": crawl_pure2, "novaler": crawl_novaler}[w]()
        except Exception as e:
            ok = False
            print("%s failed: %r" % (w, e))
    sys.exit(0 if ok else 1)
