#!/usr/bin/env python3
"""Build a demo gallery from generated sample files (no real data), optionally screenshot it.

    python demo/make_demo.py                 # builds ./demo/out, serve it with: python -m http.server -d demo/out/site
    python demo/make_demo.py --shots         # also writes assets/screenshots/*.png (needs playwright)

Requires Pillow; ffmpeg is used for the sample video/audio when available.
"""
import argparse
import datetime as dt
import functools
import http.server
import json
import math
import os
import random
import shutil
import subprocess
import sys
import tempfile
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
INGEST = os.path.join(REPO, "server", "drop-ingest.py")
NO_WINDOW = 0x08000000 if os.name == "nt" else 0

BG, MANTLE, S0, S1 = (17, 17, 27), (24, 24, 37), (49, 50, 68), (69, 71, 90)
TEXT, SUB, MUTED = (205, 214, 244), (186, 194, 222), (147, 153, 178)
BLUE, TEAL, MAUVE, GREEN, PEACH, YELLOW = (137, 180, 250), (148, 226, 213), (203, 166, 247), (166, 227, 161), \
    (250, 179, 135), (249, 226, 175)


def font(size):
    from PIL import ImageFont
    for f in ("segoeui.ttf", "DejaVuSans.ttf", "Arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(f, size)
        except OSError:
            continue
    return ImageFont.load_default()


def canvas(w=1280, h=800):
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (w, h), BG)
    return im, ImageDraw.Draw(im)


def img_chart(path):
    im, d = canvas()
    d.text((70, 50), "Backups - last 14 nights", font=font(44), fill=TEXT)
    d.text((70, 110), "GB written per night", font=font(26), fill=MUTED)
    random.seed(4)
    vals = [random.uniform(18, 46) for _ in range(14)]
    for i, v in enumerate(vals):
        x = 90 + i * 80
        h = v * 11
        d.rounded_rectangle([x, 700 - h, x + 52, 700], radius=6, fill=BLUE if i == 13 else S1)
    d.line([70, 702, 1210, 702], fill=S0, width=2)
    d.text((1000, 160), "all 14 OK", font=font(30), fill=GREEN)
    im.save(path)


def img_map(path, title="Home network"):
    im, d = canvas()
    d.text((70, 50), title, font=font(44), fill=TEXT)
    nodes = {"Internet": (640, 170), "Firewall": (640, 330), "Switch": (640, 490), "NAS": (330, 660),
             "Cameras": (540, 690), "Wi-Fi": (750, 690), "Server": (960, 660)}
    for a, b in (("Internet", "Firewall"), ("Firewall", "Switch"), ("Switch", "NAS"), ("Switch", "Cameras"),
                 ("Switch", "Wi-Fi"), ("Switch", "Server")):
        d.line([nodes[a], nodes[b]], fill=S1, width=4)
    for n, (x, y) in nodes.items():
        col = TEAL if n in ("Firewall", "Server") else BLUE
        d.rounded_rectangle([x - 90, y - 34, x + 90, y + 34], radius=14, fill=MANTLE, outline=col, width=3)
        f = font(26)
        tw = d.textlength(n, font=f)
        d.text((x - tw / 2, y - 16), n, font=f, fill=SUB)
    im.save(path)


def img_scene(path):
    """A dark generated 'render' - dusk hills and a moon."""
    from PIL import Image, ImageDraw
    w, h = 1280, 800
    im = Image.new("RGB", (w, h))
    px = im.load()
    for y in range(h):
        t = y / h
        c = (int(17 + 30 * t), int(17 + 18 * t), int(40 + 25 * t))
        for x in range(w):
            px[x, y] = c
    d = ImageDraw.Draw(im)
    d.ellipse([930, 120, 1050, 240], fill=(214, 206, 180))
    random.seed(9)
    for _ in range(90):
        x, y = random.randrange(w), random.randrange(420)
        d.point((x, y), fill=(160, 160, 190))
    for i, col in enumerate(((36, 39, 58), (30, 32, 48), (22, 23, 35))):
        pts = [(0, h)] + [(x, 520 + i * 70 + 40 * math.sin(x / (180 - i * 30) + i)) for x in range(0, w + 1, 20)] + \
            [(w, h)]
        d.polygon(pts, fill=col)
    im.save(path)


def img_stat(path):
    im, d = canvas(1080, 1080)
    d.text((80, 90), "Uptime this month", font=font(48), fill=MUTED)
    d.text((80, 260), "99.98%", font=font(200), fill=TEXT)
    d.text((80, 520), "2 blips, 9 minutes total", font=font(40), fill=SUB)
    for i in range(30):
        d.rounded_rectangle([80 + i * 31, 700, 104 + i * 31, 800], radius=4, fill=PEACH if i in (11, 23) else TEAL)
    im.save(path)


def make_video(path, frame):
    if not shutil.which("ffmpeg"):
        return False
    p = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-i", frame, "-t", "6",
                        "-vf", "scale=1280:800,zoompan=z='1+0.0015*on':d=150:s=1280x800:fps=25",
                        "-pix_fmt", "yuv420p", path], creationflags=NO_WINDOW)
    return p.returncode == 0


def make_audio(path):
    if not shutil.which("ffmpeg"):
        return False
    p = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=330:duration=8",
                        "-af", "volume=0.2", path], creationflags=NO_WINDOW)
    return p.returncode == 0


REPORT = """<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width">
<style>body{background:#11111b;color:#bac2de;font:16px/1.5 system-ui;margin:0;padding:28px;max-width:620px}
h1{color:#cdd6f4;font-size:24px}.ok{color:#a6e3a1}.card{background:#181825;border:1px solid #313244;
border-radius:12px;padding:14px 16px;margin:12px 0}</style>
<h1>Weekly server check</h1><div class=card><b class=ok>&#10003; All 6 servers healthy</b><br>
Disk under 70% everywhere. Certificates renew in 41+ days.</div>
<div class=card>Slowest backup: NAS, 38 min (was 52).</div>"""


def build(out):
    if os.path.isdir(out):
        shutil.rmtree(out)
    os.makedirs(out)
    src = tempfile.mkdtemp(prefix="drop-demo-")
    env = dict(os.environ, DROP_ROOT=out, DROP_TITLE="Drop")
    plan = []

    def add(fname, title, tags, project, days_ago, maker=None, text=None):
        p = os.path.join(src, fname)
        if maker:
            if maker(p) is False:
                return
        else:
            with open(p, "w", encoding="utf-8") as f:
                f.write(text)
        plan.append((p, title, tags, project, days_ago))

    add("backups.png", "Backup chart, 14 nights", ["report"], "Homelab", 0, img_chart)
    add("network.png", "Network map", ["diagram"], "Homelab", 1, img_map)
    add("weekly-check.html", "Weekly server check", ["report"], "Homelab", 2, text=REPORT)
    add("dusk.png", "Dusk hills render", ["art"], "Wallpapers", 3, img_scene)
    add("uptime.png", "Uptime card", ["report"], "Homelab", 5, img_stat)
    add("dusk-flyover.mp4", "Dusk flyover", ["art"], "Wallpapers", 6,
        lambda p: make_video(p, os.path.join(src, "dusk.png")))
    add("hum.m4a", "Fan hum test", ["noise"], "Garage", 9, make_audio)
    add("todo.md", "Things to fix", ["notes"], "Garage", 12,
        text="# Garage\n- replace the AP\n- label the patch panel\n")
    add("manual.pdf", "Router manual", ["docs"], "Homelab", 38,
        lambda p: canvas(850, 1100)[0].save(p, "PDF"))
    add("old-map.png", "Network map, before the rewire", ["diagram"], "Homelab", 40,
        lambda p: img_map(p, "Home network (September)"))

    now = dt.datetime.now().replace(microsecond=0)
    for p, title, tags, project, days in plan:
        args = [sys.executable, INGEST, "add", p, "--title", title, "--project", project]
        for t in tags:
            args += ["--tag", t]
        r = subprocess.run(args, env=env, capture_output=True, text=True, creationflags=NO_WINDOW)
        if r.returncode != 0:
            sys.exit("ingest failed for %s: %s" % (p, r.stderr))
        iid = r.stdout.split()[1]
        mp = os.path.join(out, "site", "i", iid, "meta.json")
        with open(mp, encoding="utf-8") as f:
            meta = json.load(f)
        meta["date"] = (now - dt.timedelta(days=days, hours=days % 5)).isoformat()
        with open(mp, "w", encoding="utf-8") as f:
            json.dump(meta, f)
    subprocess.run([sys.executable, INGEST, "reindex"], env=env, check=True, creationflags=NO_WINDOW)
    shutil.copy(os.path.join(REPO, "server", "index.html"), os.path.join(out, "site", "index.html"))
    shutil.rmtree(src, ignore_errors=True)
    print("demo gallery:", os.path.join(out, "site"), "(%d items)" % len(plan))


def shots(site, dest):
    from playwright.sync_api import sync_playwright
    os.makedirs(dest, exist_ok=True)

    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass
    handler = functools.partial(Quiet, directory=site)
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d/" % srv.server_address[1]
    with open(os.path.join(site, "index.json"), encoding="utf-8") as f:
        items = json.load(f)["items"]
    first_img = next(i["id"] for i in items if i["kind"] == "image")
    report = next(i["id"] for i in items if i["kind"] == "html")
    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=True)
        jobs = [("gallery-phone.png", {"width": 412, "height": 915}, "", 2),
                ("viewer-phone.png", {"width": 412, "height": 915}, "#" + first_img, 2),
                ("report-phone.png", {"width": 412, "height": 915}, "#" + report, 2),
                ("gallery-desktop.png", {"width": 1280, "height": 800}, "", 1)]
        for name, vp, frag, scale in jobs:
            ctx = b.new_context(viewport=vp, device_scale_factor=scale, color_scheme="dark")
            pg = ctx.new_page()
            pg.goto(base + frag)
            pg.wait_for_load_state("networkidle")
            pg.wait_for_timeout(600)
            pg.screenshot(path=os.path.join(dest, name))
            ctx.close()
            print("shot", name)
        b.close()
    srv.shutdown()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(HERE, "out"))
    ap.add_argument("--shots", action="store_true")
    a = ap.parse_args()
    build(a.out)
    if a.shots:
        shots(os.path.join(a.out, "site"), os.path.join(REPO, "assets", "screenshots"))


if __name__ == "__main__":
    main()
