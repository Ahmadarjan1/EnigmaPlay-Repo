#!/usr/bin/env python3
"""Make the store's pictures light for the receivers: they download them and decode them with a small CPU.

  icons/*        -> at most 256x256 PNG (transparency kept)
  screenshots/*  -> JPEG, at most 1280 px wide, quality 82 (a PNG screenshot gets a .jpg name and every
                    manifest that points to it is updated)

Only pictures used by a manifest in packages/ are touched; a picture already small enough is left alone.
usage: python3 tools/optimize_images.py [--dry]
"""
import glob
import io
import json
import os
import subprocess
import sys

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ICON_MAX = 256
SHOT_W = 1280
SHOT_OK_BYTES = 350 * 1024
DRY = "--dry" in sys.argv


def manifests():
    for f in sorted(glob.glob(os.path.join(ROOT, "packages", "*", "*.json"))):
        if not os.path.basename(f).startswith("_"):
            yield f


def optimize_icon(rel):
    p = os.path.join(ROOT, rel)
    im = Image.open(p)
    if max(im.size) <= ICON_MAX and os.path.getsize(p) < 60 * 1024:
        return 0
    before = os.path.getsize(p)
    im = im.convert("RGBA")
    im.thumbnail((ICON_MAX, ICON_MAX), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "PNG", optimize=True)
    if buf.tell() >= before:
        return 0
    if not DRY:
        with open(p, "wb") as f:
            f.write(buf.getvalue())
    return before - buf.tell()


def optimize_shot(rel):
    """-> (new rel path, bytes saved)"""
    p = os.path.join(ROOT, rel)
    before = os.path.getsize(p)
    im = Image.open(p)
    is_jpg = rel.lower().endswith((".jpg", ".jpeg"))
    if is_jpg and im.size[0] <= SHOT_W and before <= SHOT_OK_BYTES:
        return rel, 0
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bg.paste(im, mask=im.split()[-1])
        im = bg
    else:
        im = im.convert("RGB")
    if im.size[0] > SHOT_W:
        im = im.resize((SHOT_W, round(im.size[1] * SHOT_W / im.size[0])), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=82, optimize=True, progressive=True)
    if buf.tell() >= before:
        return rel, 0
    new_rel = rel if is_jpg else os.path.splitext(rel)[0] + ".jpg"
    if not DRY:
        with open(os.path.join(ROOT, new_rel), "wb") as f:
            f.write(buf.getvalue())
        if new_rel != rel:
            subprocess.call(["git", "-C", ROOT, "rm", "-q", "--cached", "--ignore-unmatch", rel])
            os.remove(p)
    return new_rel, before - buf.tell()


def main():
    icons, shots = set(), set()
    for f in manifests():
        d = json.load(open(f, encoding="utf-8"))
        if d.get("icon") and not d["icon"].startswith("http"):
            icons.add(d["icon"])
        for s in d.get("screenshots") or []:
            if not s.startswith("http"):
                shots.add(s)
    saved = 0
    for rel in sorted(icons):
        if os.path.exists(os.path.join(ROOT, rel)):
            saved += optimize_icon(rel)
    renamed = {}
    for rel in sorted(shots):
        if os.path.exists(os.path.join(ROOT, rel)):
            new_rel, s = optimize_shot(rel)
            saved += s
            if new_rel != rel:
                renamed[rel] = new_rel
    if renamed and not DRY:
        for f in manifests():
            text = open(f, encoding="utf-8").read()
            d = json.loads(text)
            sh = d.get("screenshots") or []
            if any(s in renamed for s in sh):
                d["screenshots"] = [renamed.get(s, s) for s in sh]
                indent = 1 if text.startswith("{\n \"") else 2
                with open(f, "w", encoding="utf-8") as fh:
                    fh.write(json.dumps(d, ensure_ascii=False, indent=indent) + "\n")
    print("saved %.1f MB; %d screenshots now JPEG" % (saved / 1048576.0, len(renamed)))


if __name__ == "__main__":
    main()
