#!/usr/bin/env python3
"""drop-ingest - the server half of Drop. Install as /usr/local/bin/drop-ingest.

  drop-ingest add <path> [--name N] [--title T] [--tag x --tag y] [--project P]
  drop-ingest list
  drop-ingest rm <id>                 # moves the item to $DROP_ROOT/trash (recoverable)
  drop-ingest tag <id> [--add x] [--remove y] [--title T] [--project P]
  drop-ingest reindex                 # rebuild index.json from every item's meta.json

Layout under $DROP_ROOT (default /srv/drop):
  site/index.html  site/index.json  site/i/<id>/<file>  site/i/<id>/thumb.jpg  site/i/<id>/meta.json
  inbox/   uploads land here before ingest
  trash/   removed items

Each item's meta.json is the source of truth; index.json is derived from them, so a corrupt index never
loses data. Item ids are the first 10 hex chars of the file's SHA-1, so the same file is never stored twice.

Environment:
  DROP_ROOT   data root (default /srv/drop)
  DROP_TITLE  gallery title written into index.json (default "Drop")
"""
import argparse
import datetime as dt
import hashlib
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys

__version__ = "1.0.0"

ROOT = os.environ.get("DROP_ROOT", "/srv/drop")
SITE = os.path.join(ROOT, "site")
ITEMS = os.path.join(SITE, "i")
INDEX = os.path.join(SITE, "index.json")
TRASH = os.path.join(ROOT, "trash")
TITLE = os.environ.get("DROP_TITLE", "Drop")
THUMB_W = 480
ID_RE = re.compile(r"^[0-9a-f]{10}$")

IMG = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".heic"}
VID = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi"}
AUD = {".mp3", ".m4a", ".wav", ".ogg", ".flac", ".aac", ".m4b"}
TXT = {".txt", ".md", ".log", ".json", ".csv"}


def kind(ext):
    ext = ext.lower()
    if ext in IMG:
        return "image"
    if ext in VID:
        return "video"
    if ext in AUD:
        return "audio"
    if ext == ".pdf":
        return "pdf"
    if ext in {".html", ".htm"}:
        return "html"
    if ext in TXT:
        return "text"
    return "other"


def safe_name(name):
    """Reduce a requested file name to a plain base name. Rejects empty and dot names."""
    base = os.path.basename(name.replace("\\", "/")).strip()
    base = "".join(c for c in base if c >= " " and c not in '<>:"|?*')
    if not base or base.startswith(".") or base in {"meta.json", "thumb.jpg"}:
        raise ValueError("bad file name: %r" % name)
    return base


def check_id(iid):
    if not ID_RE.match(iid or ""):
        sys.exit("bad id: %r (expected 10 hex characters)" % iid)
    return iid


def sh(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def thumb_image(src, dst):
    from PIL import Image, ImageOps
    with Image.open(src) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        w, h = im.size
        im.thumbnail((THUMB_W, THUMB_W * 2))
        im.save(dst, "JPEG", quality=78)
    return w, h


def thumb_video(src, dst):
    meta = {}
    p = sh(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
            "stream=width,height:format=duration", "-of", "json", src])
    try:
        j = json.loads(p.stdout)
        st = (j.get("streams") or [{}])[0]
        meta = {"w": st.get("width"), "h": st.get("height"),
                "dur": round(float(j.get("format", {}).get("duration", 0)), 1)}
    except (ValueError, KeyError, TypeError):
        pass
    t = 1 if meta.get("dur", 0) > 2 else 0
    sh(["ffmpeg", "-y", "-loglevel", "error", "-ss", str(t), "-i", src, "-frames:v", "1",
        "-vf", "scale=%d:-2" % THUMB_W, "-q:v", "4", dst])
    return meta


def thumb_generic(label, dst):
    """Dark placeholder card for files with no picture (pdf, audio, zip...)."""
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (THUMB_W, 360), (24, 24, 37))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([170, 80, 310, 250], radius=12, outline=(137, 180, 250), width=4)
    d.polygon([(270, 80), (310, 120), (270, 120)], fill=(69, 71, 90))
    text = label.upper()[:8]
    f = label_font(30)
    try:
        tw = d.textlength(text, font=f)
    except AttributeError:
        tw = 6 * len(text)
    d.text((240 - tw / 2, 150), text, fill=(186, 194, 222), font=f)
    im.save(dst, "JPEG", quality=80)


def label_font(size):
    from PIL import ImageFont
    for f in ("DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "arialbd.ttf"):
        try:
            return ImageFont.truetype(f, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=size)  # Pillow 10.1+
    except TypeError:
        return ImageFont.load_default()


def faststart(path):
    """Move the MP4 index to the front so phones can start playing before the download finishes."""
    tmp = path + ".fs.mp4"
    p = sh(["ffmpeg", "-y", "-loglevel", "error", "-i", path, "-c", "copy",
            "-movflags", "+faststart", "-f", "mp4", tmp])
    if p.returncode == 0 and os.path.exists(tmp) and os.path.getsize(tmp) > 0:
        os.replace(tmp, path)
    elif os.path.exists(tmp):
        os.remove(tmp)


def write_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)
    os.replace(tmp, path)


def reindex():
    items = []
    if os.path.isdir(ITEMS):
        for d in os.listdir(ITEMS):
            mp = os.path.join(ITEMS, d, "meta.json")
            if os.path.exists(mp):
                try:
                    with open(mp, encoding="utf-8") as f:
                        items.append(json.load(f))
                except (OSError, ValueError) as e:
                    print("skip unreadable meta:", d, type(e).__name__, file=sys.stderr)
    items.sort(key=lambda m: m.get("date", ""), reverse=True)
    write_json(INDEX, {"title": TITLE, "updated": dt.datetime.now().isoformat(timespec="seconds"), "items": items})
    return items


def sha1_id(path):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:10]


def cmd_add(a):
    src = a.path
    if not os.path.isfile(src):
        sys.exit("no such file: %s" % src)
    try:
        name = safe_name(a.name or os.path.basename(src))
    except ValueError as e:
        sys.exit(str(e))
    ext = os.path.splitext(name)[1]
    iid = sha1_id(src)
    d = os.path.join(ITEMS, iid)
    if os.path.exists(os.path.join(d, "meta.json")):
        print("EXISTS", iid)
        if a.move:
            os.remove(src)
        return
    os.makedirs(d, exist_ok=True)
    dest = os.path.join(d, name)
    if a.move:
        shutil.move(src, dest)
    else:
        shutil.copy2(src, dest)
    k = kind(ext)
    extra = {}
    thumb = os.path.join(d, "thumb.jpg")
    try:
        if k == "image":
            w, h = thumb_image(dest, thumb)
            extra = {"w": w, "h": h}
        elif k == "video":
            if ext.lower() in {".mp4", ".mov", ".m4v"}:
                faststart(dest)
            extra = thumb_video(dest, thumb)
        if not os.path.exists(thumb):
            thumb_generic(k if k != "other" else ext.strip(".") or "file", thumb)
    except Exception as e:  # a bad thumbnail must never lose the file
        print("thumb warning:", type(e).__name__, e, file=sys.stderr)
        if not os.path.exists(thumb):
            try:
                thumb_generic(k, thumb)
            except Exception:
                pass
    meta = {"id": iid, "file": name, "title": a.title or os.path.splitext(name)[0], "tags": sorted(set(a.tag)),
            "project": a.project or "", "date": dt.datetime.now().isoformat(timespec="seconds"),
            "size": os.path.getsize(dest), "kind": k,
            "mime": mimetypes.guess_type(name)[0] or "application/octet-stream", **extra}
    write_json(os.path.join(d, "meta.json"), meta)
    reindex()
    print("ADDED", iid, k, meta["size"])


def load_meta(iid):
    mp = os.path.join(ITEMS, check_id(iid), "meta.json")
    if not os.path.exists(mp):
        sys.exit("no such id: %s" % iid)
    with open(mp, encoding="utf-8") as f:
        return mp, json.load(f)


def cmd_tag(a):
    mp, m = load_meta(a.id)
    tags = (set(m.get("tags", [])) | set(a.add or [])) - set(a.remove or [])
    m["tags"] = sorted(tags)
    if a.title:
        m["title"] = a.title
    if a.project is not None:
        m["project"] = a.project
    write_json(mp, m)
    reindex()
    print("UPDATED", a.id)


def cmd_rm(a):
    d = os.path.join(ITEMS, check_id(a.id))
    if not os.path.isdir(d):
        sys.exit("no such id: %s" % a.id)
    os.makedirs(TRASH, exist_ok=True)
    shutil.move(d, os.path.join(TRASH, a.id + "-" + dt.datetime.now().strftime("%Y%m%d%H%M%S")))
    reindex()
    print("MOVED TO TRASH", a.id)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="drop-ingest", description="Add and manage items in a Drop gallery.")
    ap.add_argument("--version", action="version", version="%(prog)s " + __version__)
    sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("add", help="add a file")
    p.add_argument("path")
    p.add_argument("--name", help="stored file name (default: the source name)")
    p.add_argument("--title")
    p.add_argument("--tag", action="append", default=[])
    p.add_argument("--project", default="")
    p.add_argument("--move", action="store_true", help="move the source instead of copying it (used for uploads)")
    sp.add_parser("list", help="list items, newest first")
    sp.add_parser("reindex", help="rebuild index.json")
    p = sp.add_parser("rm", help="move an item to trash")
    p.add_argument("id")
    p = sp.add_parser("tag", help="edit tags, title or project")
    p.add_argument("id")
    p.add_argument("--add", action="append")
    p.add_argument("--remove", action="append")
    p.add_argument("--title")
    p.add_argument("--project")
    a = ap.parse_args(argv)
    os.makedirs(ITEMS, exist_ok=True)
    if a.cmd == "add":
        cmd_add(a)
    elif a.cmd == "list":
        for m in reindex():
            print(m["id"], m["date"][:10], m["kind"], m["size"], m["title"], m.get("tags", []))
    elif a.cmd == "reindex":
        print(len(reindex()), "items")
    elif a.cmd == "rm":
        cmd_rm(a)
    elif a.cmd == "tag":
        cmd_tag(a)


if __name__ == "__main__":
    main()
